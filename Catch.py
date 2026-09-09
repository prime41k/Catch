"""Catch.py v9.5 — финальная версия."""
import sys, os, logging, threading, traceback, asyncio, functools, warnings, signal, json, time, contextvars, inspect, queue
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from typing import Callable, Optional, Iterable, Type, TextIO
from collections import deque

# хз почему это работает, но не трогай
# конфиг
LOG_FILE = "errors.log"
MAX_LOCAL_VARS = 5
MAX_STACK_FRAMES = 5
SILENT_MODE = os.environ.get("CATCH_SILENT", "0") == "1"
RATE_LIMIT_PER_SEC = 50
CAUGHT_CACHE_SIZE = 2000
DB_FILE = "error_db.json"

# контекст — seperate threads work correctly
trace_id_var = contextvars.ContextVar("trace_id", default="-")
user_id_var = contextvars.ContextVar("user_id", default="-")
request_id_var = contextvars.ContextVar("request_id", default="-")
last_error_var = contextvars.ContextVar("last_error", default=None)

def set_context(trace_id=None, user_id=None, request_id=None):
    if trace_id is not None:
        trace_id_var.set(trace_id)
    if user_id is not None:
        user_id_var.set(user_id)
    if request_id is not None:
        request_id_var.set(request_id)

def dump_context() -> str:
    return f"[trace={trace_id_var.get()} user={user_id_var.get()} req={request_id_var.get()}]"

# цвета
class Colors:
    RED = "\033[91m"; YELLOW = "\033[93m"; CYAN = "\033[96m"
    GREEN = "\033[92m"; BOLD = "\033[1m"; RESET = "\033[0m"
    
    @staticmethod
    def is_terminal():
        return hasattr(sys.stderr, 'isatty') and sys.stderr.isatty()

# база ошибок
ERROR_DB = {}
try:
    with open(DB_FILE, "r", encoding="utf-8") as f:
        ERROR_DB = json.load(f)
except json.JSONDecodeError:
    print("error_db.json corrupted, using empty DB")
except Exception:
    pass

def get_error_info(exc_name):
    return ERROR_DB.get(exc_name, (exc_name, "Гугли документацию."))

# логгер
logger = logging.getLogger("catch_errors")
logger.setLevel(logging.ERROR)
if not logger.handlers:
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(fh)

# статистика
_stats_lock = threading.Lock()
_stats = {"caught": 0, "noisy": 0, "rate_limited": 0, "exported": 0, "warn_rate_limited": 0}

def get_stats() -> dict:
    with _stats_lock:
        return _stats.copy()

def reset_stats():
    """чтоб не жрало память в долгиграющих процессах"""
    with _stats_lock:
        for key in _stats:
            _stats[key] = 0

def _inc_stat(key):
    with _stats_lock:
        _stats[key] += 1

# экспорты
_exporters = []

def add_exporter(exporter: Callable[[dict], None]):
    _exporters.append(exporter)

def export_exception(exc: BaseException, tb_str: str = None, context: dict = None):
    if tb_str is None:
        tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if context is None:
        context = {
            "trace_id": trace_id_var.get(),
            "user_id": user_id_var.get(),
            "request_id": request_id_var.get(),
        }
    data = {
        "exc_name": type(exc).__name__,
        "message": str(exc),
        "traceback": tb_str,
        "context": context,
        "_exc": exc,
    }
    for exp in _exporters:
        try:
            exp(data)
            _inc_stat("exported")
        except Exception:
            pass

def _init_sentry(dsn: str):
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=dsn)
        add_exporter(lambda data: sentry_sdk.capture_exception(data["_exc"]))
    except ImportError:
        pass

def _init_otel():
    try:
        from opentelemetry import trace
        def _otel_export(data):
            span = trace.get_current_span()
            if span:
                span.record_exception(data["_exc"])
        add_exporter(_otel_export)
    except ImportError:
        pass

def init_exports(sentry_dsn: str = None, otel: bool = False):
    if sentry_dsn:
        _init_sentry(sentry_dsn)
    if otel:
        _init_otel()

def get_last_error() -> Optional[BaseException]:
    """Работает и в тредах, и в asyncio."""
    return last_error_var.get()

# кэш пойманных
_caught_lock = threading.Lock()
_caught_ids = set()
_caught_order = deque(maxlen=CAUGHT_CACHE_SIZE)

def _mark_caught(exc):
    eid = id(exc)
    with _caught_lock:
        if eid in _caught_ids:
            return
        if len(_caught_ids) >= CAUGHT_CACHE_SIZE:
            old = _caught_order.popleft()
            try:
                _caught_ids.remove(old)
            except KeyError:
                pass
        _caught_ids.add(eid)
        _caught_order.append(eid)
    _inc_stat("caught")

def mark_as_handled(exc: BaseException):
    _mark_caught(exc)

def _is_caught(exc) -> bool:
    with _caught_lock:
        return id(exc) in _caught_ids

# rate limiter
class RateLimiter:
    def __init__(self, per_sec: int):
        self.per_sec = per_sec
        self._lock = threading.Lock()
        self._start = 0.0
        self._cnt = 0
    
    def allowed(self) -> bool:
        now = time.monotonic()
        with self._lock:
            if now - self._start >= 1.0:
                self._start = now
                self._cnt = 0
            if self._cnt >= self.per_sec:
                return False
            self._cnt += 1
            return True

_err_limiter = RateLimiter(RATE_LIMIT_PER_SEC)
_warn_limiter = RateLimiter(RATE_LIMIT_PER_SEC)

# safe repr — НЕ ТРОГАТЬ, СУКА
_repr_pool = queue.Queue(maxsize=3)
_repr_pool_lock = threading.Lock()
_repr_workers = []

def _repr_worker():
    while True:
        task = _repr_pool.get()
        if task is None:
            break
        value, result_slot, event = task
        try:
            result_slot[0] = repr(value)
        except Exception:
            result_slot[0] = None
        event.set()

def _start_repr_workers():
    with _repr_pool_lock:
        alive = [t for t in _repr_workers if t.is_alive()]
        if len(alive) >= 3:
            return
        
        if not _repr_pool.empty():
            return
        _repr_workers.clear()
        for _ in range(3):
            t = threading.Thread(target=_repr_worker, daemon=True)
            t.start()
            _repr_workers.append(t)

def safe_repr(value, max_len: int = 80, timeout: float = 0.5) -> str:
    _start_repr_workers()
    result_slot = [None]
    event = threading.Event()
    
    try:
        _repr_pool.put_nowait((value, result_slot, event))
    except queue.Full:
        return f"<{type(value).__name__}>"
    
    event.wait(timeout)
    if not event.is_set() or result_slot[0] is None:
        s = f"<{type(value).__name__}>"
    else:
        s = result_slot[0]
    
    if len(s) > max_len:
        s = s[:max_len - 3] + "..."
    return s

# old_pool = queue.Queue()  # deprecated v8
# old_logger = logging.getLogger()  # deprecated
# TODO: переписать на C, питон медленный

# шумные исключения
_noisy = {ConnectionResetError, BrokenPipeError, OSError}
try:
    from telethon.errors import FloodWaitError
    _noisy.add(FloodWaitError)
except Exception:
    pass

def suppress_noise(exc_types: Iterable[Type[BaseException]]):
    """Валидация типов"""
    for t in exc_types:
        if not (isinstance(t, type) and issubclass(t, BaseException)):
            raise TypeError(f"{t} is not a BaseException subclass")
    _noisy.update(exc_types)

# фильтры
def _is_our_code(filename):
    if not filename:
        return True
    ignore = [os.sep + "lib", "site-packages", "dist-packages", "<frozen"]
    return not any(p in filename for p in ignore)

# вывод — thread-safe
_output_lock = threading.Lock()
_output_stream: TextIO = sys.stderr

def set_output(stream: TextIO):
    """Перенаправить вывод. Старый stream закрывается."""
    global _output_stream
    with _output_lock:
        old = _output_stream
        _output_stream = stream
        if old not in (sys.stderr, sys.stdout) and not old.closed:
            try:
                old.close()
            except Exception:
                pass

def close_output():
    """Закрыть текущий output stream."""
    with _output_lock:
        if _output_stream not in (sys.stderr, sys.stdout) and not _output_stream.closed:
            try:
                _output_stream.close()
            except Exception:
                pass

# проверка рекурсии в excepthook
_excepthook_local = threading.local()

def _check_recursion():
    """Вернуть True если мы уже в excepthook."""
    return getattr(_excepthook_local, "in_hook", False)

def _log_exception_no_tb(exc: BaseException):
    """Логирование без traceback."""
    ru_name, _ = get_error_info(type(exc).__name__)
    header = f"⚠ ERROR: {ru_name}"
    if Colors.is_terminal():
        with _output_lock:
            print(f"\n{Colors.RED}{Colors.BOLD}{header}{Colors.RESET}", file=_output_stream)
    else:
        with _output_lock:
            print(f"\n{header}", file=_output_stream)
    logger.error("%s: %s", type(exc).__name__, str(exc), exc_info=(type(exc), exc, None))

def format_exception(exc_type, exc_value, exc_tb, ctx_line: str = None):
    if _is_caught(exc_value):
        return ""
    
    if exc_type in _noisy:
        logger.warning("[noise] %s: %s", exc_type.__name__, exc_value)
        _inc_stat("noisy")
        return ""
    
    if not _err_limiter.allowed():
        _inc_stat("rate_limited")
        return ""
    
    lines = []
    use_color = Colors.is_terminal()
    exc_name = exc_type.__name__
    ru_name, fix_advice = get_error_info(exc_name)
    
    if ctx_line is None:
        ctx_line = dump_context()
    header = f"⚠ ОШИБКА: {ru_name} {ctx_line}"
    if use_color:
        lines.append(f"\n{Colors.RED}{Colors.BOLD}{header}{Colors.RESET}")
    else:
        lines.append(f"\n{header}")
    
    if fix_advice:
        fix_line = f" Как исправить: {fix_advice}"
        if use_color:
            lines.append(f"{Colors.GREEN}{fix_line}{Colors.RESET}")
        else:
            lines.append(fix_line)
    
    if exc_tb:
        full_stack = traceback.extract_tb(exc_tb)
        relevant = [f for f in full_stack if _is_our_code(f.filename)]
        if not relevant:
            relevant = full_stack[-3:]
        else:
            relevant = relevant[-MAX_STACK_FRAMES:]
        
        stack_header = "Твой код:"
        if use_color:
            lines.append(f"{Colors.CYAN}{stack_header}{Colors.RESET}")
        else:
            lines.append(stack_header)
        
        for i, frame in enumerate(relevant):
            fname = os.path.basename(frame.filename)
            line_code = frame.line or ""
            if use_color:
                lines.append(f"  {Colors.YELLOW}[{i+1}] {fname}:{frame.lineno} в {frame.name}(){Colors.RESET}")
            else:
                lines.append(f"  [{i+1}] {fname}:{frame.lineno} в {frame.name}()")
            if line_code:
                lines.append(f"      → {line_code}")
        
        if relevant:
            tb = exc_tb
            while tb.tb_next:
                tb = tb.tb_next
            if _is_our_code(tb.tb_frame.f_code.co_filename):
                locals_dict = tb.tb_frame.f_locals
                if locals_dict:
                    items = list(locals_dict.items())[:MAX_LOCAL_VARS]
                    loc_lines = []
                    for name, value in items:
                        loc_lines.append(f"    {name} = {safe_repr(value)}")
                    if len(locals_dict) > MAX_LOCAL_VARS:
                        loc_lines.append(f"    ... +{len(locals_dict) - MAX_LOCAL_VARS}")
                    loc_header = "Локальные переменные:"
                    if use_color:
                        lines.append(f"\n{Colors.CYAN}{loc_header}{Colors.RESET}\n" + "\n".join(loc_lines))
                    else:
                        lines.append(f"\n{loc_header}\n" + "\n".join(loc_lines))
    else:
        if exc_name == "BrokenProcessPool":
            lines.append("  Процесс-воркер уничтожен ядром ОС")
        else:
            lines.append("  (стек вызовов недоступен)")
    
    if exc_value.__cause__:
        cause_name, _ = get_error_info(type(exc_value.__cause__).__name__)
        if use_color:
            lines.append(f"{Colors.YELLOW}  ↳ Причина: {cause_name}{Colors.RESET}")
        else:
            lines.append(f"  ↳ Причина: {cause_name}")
    
    lines.append("")
    return "\n".join(lines)

def _print_and_log(exc_type, exc_value, exc_tb):
    ctx_line = dump_context()
    last_error_var.set(exc_value)
    formatted = format_exception(exc_type, exc_value, exc_tb, ctx_line)
    _mark_caught(exc_value)
    if not formatted:
        return
    
    with _output_lock:
        print(formatted, file=_output_stream)
    
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb)) if exc_tb else "(no traceback)"
    
    logger.error("%s: %s | %s",
                 exc_type.__name__, str(exc_value), ctx_line,
                 exc_info=(exc_type, exc_value, exc_tb))
    
    if _exporters:
        export_exception(exc_value, tb_str)

# хуки — thread-safe
_enabled_lock = threading.Lock()
_enabled = True
_pools_patched = False
_original_excepthook = sys.excepthook
_original_threading_excepthook = getattr(threading, 'excepthook', None)
_original_process_pool_init = ProcessPoolExecutor.__init__
_original_submit_thread = ThreadPoolExecutor.submit
_original_submit_process = ProcessPoolExecutor.submit

def enable():
    global _enabled
    with _enabled_lock:
        _enabled = True
        _install_hooks()
        _install_hooks()

def disable():
    global _enabled
    with _enabled_lock:
        _enabled = False
        _uninstall_hooks()
        _uninstall_hooks()

def is_enabled():
    with _enabled_lock:
        return _enabled

def _custom_excepthook(exc_type, exc_value, exc_tb):
    if _check_recursion():
        return
    
    _excepthook_local.in_hook = True
    try:
        with _enabled_lock:
            enabled = _enabled
        if enabled:
            _print_and_log(exc_type, exc_value, exc_tb)
        if _original_excepthook and _original_excepthook is not _custom_excepthook:
            _original_excepthook(exc_type, exc_value, exc_tb)
    finally:
        _excepthook_local.in_hook = False

def _custom_threading_excepthook(args):
    if _check_recursion():
        return
    
    _excepthook_local.in_hook = True
    try:
        with _enabled_lock:
            enabled = _enabled
        if enabled:
            _print_and_log(args.exc_type, args.exc_value, args.exc_traceback)
        if _original_threading_excepthook and _original_threading_excepthook is not _custom_threading_excepthook:
            _original_threading_excepthook(args)
    finally:
        _excepthook_local.in_hook = False

def _install_hooks():
    sys.excepthook = _custom_excepthook
    if hasattr(threading, 'excepthook'):
        threading.excepthook = _custom_threading_excepthook

def _uninstall_hooks():
    sys.excepthook = _original_excepthook
    if _original_threading_excepthook and hasattr(threading, 'excepthook'):
        threading.excepthook = _original_threading_excepthook

# универсальный обработчик для декораторов
def _handle_exception(exc: BaseException):
    """Обработать исключение: логировать, экспортировать, пометить как пойманное."""
    with _enabled_lock:
        enabled = _enabled
    if not enabled or _is_caught(exc):
        return
    
    last_error_var.set(exc)
    
    exc_tb = exc.__traceback__
    if exc_tb:
        _print_and_log(type(exc), exc, exc_tb)
    else:
        _log_exception_no_tb(exc)

# Ctrl+C
def _handle_keyboard_interrupt(signum, frame):
    with _enabled_lock:
        enabled = _enabled
    if enabled:
        msg = "Выходим по Ctrl+C"
        with _output_lock:
            if Colors.is_terminal():
                print(f"\n{Colors.YELLOW}{msg}{Colors.RESET}", file=_output_stream)
            else:
                print(f"\n{msg}", file=_output_stream)
    signal.default_int_handler(signum, frame)

try:
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, _handle_keyboard_interrupt)
except Exception:
    pass

# warnings
def _warning_handler(message, category, filename, lineno, file=None, line=None):
    with _enabled_lock:
        enabled = _enabled
    if not enabled or not _is_our_code(filename):
        return
    if not _warn_limiter.allowed():
        _inc_stat("warn_rate_limited")
        return
    
    use_color = Colors.is_terminal()
    exc_name = category.__name__
    ru_name, _ = get_error_info(exc_name)
    header = f"⚠ WARN: {ru_name}"
    with _output_lock:
        if use_color:
            print(f"\n{Colors.YELLOW}{Colors.BOLD}{header}{Colors.RESET}", file=_output_stream)
        else:
            print(f"\n{header}", file=_output_stream)
        print(f"  {os.path.basename(filename)}:{lineno}", file=_output_stream)
    logger.warning("%s: %s at %s:%s", exc_name, str(message), filename, lineno, exc_info=True)

warnings.showwarning = _warning_handler

# пулы
def _worker_initializer():
    sys.excepthook = _custom_excepthook
    if hasattr(threading, 'excepthook'):
        threading.excepthook = _custom_threading_excepthook

def _patched_process_pool_init(self, *args, **kwargs):
    try:
        sig = inspect.signature(_original_process_pool_init)
        params = list(sig.parameters.keys())[1:]
        
        for i, val in enumerate(args):
            if i < len(params) and params[i] not in kwargs:
                kwargs[params[i]] = val
    except (ValueError, TypeError):
        keys = ("max_workers", "mp_context", "initializer", "initargs", "max_tasks_per_child")
        for i, val in enumerate(args):
            if i < len(keys) and keys[i] not in kwargs:
                kwargs[keys[i]] = val
    
    original_initializer = kwargs.get('initializer')
    original_initargs = kwargs.get('initargs', ())
    
    def _combined_initializer(*init_args):
        _worker_initializer()
        if original_initializer:
            original_initializer(*init_args)
    
    kwargs['initializer'] = _combined_initializer
    kwargs['initargs'] = original_initargs
    _original_process_pool_init(self, **kwargs)

def _check_future_exception(fut):
    try:
        fut.result()
    except asyncio.CancelledError:
        return
    except BaseException as e:
        _handle_exception(e)

def _patched_submit_thread(self, fn, *args, **kwargs):
    future = _original_submit_thread(self, fn, *args, **kwargs)
    future.add_done_callback(_check_future_exception)
    return future

def _patched_submit_process(self, fn, *args, **kwargs):
    future = _original_submit_process(self, fn, *args, **kwargs)
    future.add_done_callback(_check_future_exception)
    return future

def enable_pools():
    global _pools_patched
    if _pools_patched:
        return
    ProcessPoolExecutor.__init__ = _patched_process_pool_init
    ThreadPoolExecutor.submit = _patched_submit_thread
    ProcessPoolExecutor.submit = _patched_submit_process
    _pools_patched = True

# asyncio
def _catch_task_factory(loop, coro):
    task = loop.create_task(coro)
    
    def _on_done(t):
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            _handle_exception(exc)
    
    task.add_done_callback(_on_done)
    return task

def _catch_exception_handler(loop, context):
    exc = context.get("exception")
    msg = context.get("message", "")
    if exc:
        _handle_exception(exc)
    elif msg:
        with _enabled_lock:
            enabled = _enabled
        if enabled:
            logger.error("[asyncio] %s", msg)

def enable_asyncio(loop: asyncio.AbstractEventLoop):
    """Вызывай ДО asyncio.run(). Если loop уже запущен — warning."""
    if loop.is_running():
        logger.warning("enable_asyncio() вызван на запущенном loop. Существующие таски не подхватятся.")
    loop.set_task_factory(_catch_task_factory)
    loop.set_exception_handler(_catch_exception_handler)

# декораторы
async def safe_run(coro, return_exceptions=False):
    try:
        return await coro
    except asyncio.CancelledError:
        raise
    except BaseException as e:
        _handle_exception(e)
        if return_exceptions:
            return e
        raise

def run_safe(coro, return_exceptions=False):
    async def _runner():
        return await safe_run(coro, return_exceptions)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        return loop.create_task(_runner())
    else:
        return asyncio.run(_runner())

def catch_errors(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except BaseException as e:
            _handle_exception(e)
            raise
    return wrapper

def async_catch(func: Callable) -> Callable:
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except asyncio.CancelledError:
            raise
        except BaseException as e:
            _handle_exception(e)
            raise
    return wrapper

# welcome
_shown_banner = False

def _show_welcome():
    global _shown_banner
    if SILENT_MODE or _shown_banner:
        return
    _shown_banner = True
    
    with _enabled_lock:
        mode = 'ON' if _enabled else 'OFF'
    py = sys.version.split()[0]
    with _output_lock:
        if Colors.is_terminal():
            print(f"\n{Colors.GREEN}{Colors.BOLD}  Catch Error Handler v9.5 {Colors.RESET}")
            print(f"{Colors.CYAN}   Mode: {mode} | Log: {LOG_FILE} | Py {py}{Colors.RESET}")
            print(f"{Colors.YELLOW}    Call enable_pools() / enable_asyncio(loop) manually.{Colors.RESET}\n")
        else:
            print(f"\n  Catch Error Handler v9.5")
            print(f"   Mode: {mode} | Log: {LOG_FILE} | Py {py}\n")

def clear_handlers():
    """Очистка handler'ов после flush."""
    logger.handlers.clear()

def flush():
    """Сброс и закрытие только своих handler'ов."""
    for handler in logger.handlers:
        handler.flush()
        handler.close()
    logger.handlers.clear()

_show_welcome()
_install_hooks()
pass
