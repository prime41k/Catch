"""
Catch.py v6.2 — Финальная версия. Полный перехват ошибок Python.
Multiprocessing (initializer), Futures, Asyncio, Threads, Warnings.
"""

import sys
import os
import logging
import threading
import traceback
import asyncio
import functools
import warnings
import signal
import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from typing import Optional, Callable, Any
from collections import deque

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

LOG_FILE = "errors.log"
MAX_LOCAL_VARS = 5
MAX_STACK_FRAMES = 3
INCLUDE_GLOBALS = False

class Colors:
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    @staticmethod
    def is_terminal() -> bool:
        return hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()

ERROR_TRANSLATIONS = {
    "ZeroDivisionError": "Деление на ноль",
    "FileNotFoundError": "Файл не найден",
    "PermissionError": "Нет прав доступа",
    "KeyError": "Ключ не найден в словаре",
    "IndexError": "Индекс за пределами списка",
    "TypeError": "Неверный тип данных",
    "ValueError": "Неверное значение",
    "AttributeError": "Атрибут не найден",
    "ImportError": "Ошибка импорта",
    "ModuleNotFoundError": "Модуль не установлен",
    "NameError": "Переменная не определена",
    "SyntaxError": "Синтаксическая ошибка",
    "IndentationError": "Ошибка отступов",
    "TabError": "Неверная табуляция",
    "RuntimeError": "Ошибка выполнения",
    "RecursionError": "Превышена глубина рекурсии",
    "MemoryError": "Недостаточно памяти",
    "OverflowError": "Число слишком большое",
    "StopIteration": "Итератор исчерпан",
    "AssertionError": "Утверждение ложно",
    "ConnectionError": "Ошибка соединения",
    "TimeoutError": "Таймаут",
    "JSONDecodeError": "Ошибка JSON",
    "UnicodeDecodeError": "Ошибка декодирования",
    "BrokenProcessPool": "Процесс-воркер уничтожен",
}

def translate_error(exc_name: str, exc_msg: str) -> str:
    ru_name = ERROR_TRANSLATIONS.get(exc_name, exc_name)
    return f"{ru_name}: {exc_msg}" if exc_msg else ru_name

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

logger = logging.getLogger("catch_errors")
logger.setLevel(logging.ERROR)

if not logger.handlers:
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(fh)

# ============================================================================
# ЗАЩИТА ОТ ДВОЙНОЙ ОБРАБОТКИ
# ============================================================================

_processed_ids: deque = deque(maxlen=1000)
_lock = threading.Lock()

def _is_already_processed(exc: BaseException) -> bool:
    exc_id = id(exc)
    with _lock:
        if exc_id in _processed_ids:
            return True
        if getattr(exc, "_smart_caught", False):
            return True
        _processed_ids.append(exc_id)
        exc._smart_caught = True  # type: ignore
        return False

# ============================================================================
# ФОРМАТИРОВАНИЕ
# ============================================================================

def format_exception(exc_type, exc_value, exc_tb) -> str:
    if _is_already_processed(exc_value):
        return ""

    lines = []
    use_color = Colors.is_terminal()

    exc_name = exc_type.__name__
    exc_msg = str(exc_value)
    translated = translate_error(exc_name, exc_msg)

    header = f"⚠ ОШИБКА: {translated}"
    if use_color:
        lines.append(f"\n{Colors.RED}{Colors.BOLD}{header}{Colors.RESET}")
    else:
        lines.append(f"\n{header}")

    if exc_tb:
        tb_list = traceback.extract_tb(exc_tb)
        relevant = tb_list[-MAX_STACK_FRAMES:] if len(tb_list) > MAX_STACK_FRAMES else tb_list

        stack_header = "📍 Стек вызовов:"
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

        # Локальные переменные из последнего фрейма
        tb = exc_tb
        while tb.tb_next:
            tb = tb.tb_next
        frame = tb.tb_frame

        locals_dict = frame.f_locals
        if locals_dict:
            items = list(locals_dict.items())[:MAX_LOCAL_VARS]
            loc_lines = []
            for name, value in items:
                try:
                    val_str = repr(value)
                    if len(val_str) > 100:
                        val_str = val_str[:97] + "..."
                    loc_lines.append(f"    {name} = {val_str}")
                except:
                    loc_lines.append(f"    {name} = <error>")

            if len(locals_dict) > MAX_LOCAL_VARS:
                loc_lines.append(f"    ... и ещё {len(locals_dict) - MAX_LOCAL_VARS}")

            loc_header = "🔧 Локальные переменные:"
            if use_color:
                lines.append(f"\n{Colors.CYAN}{loc_header}{Colors.RESET}\n" + "\n".join(loc_lines))
            else:
                lines.append(f"\n{loc_header}\n" + "\n".join(loc_lines))

        if INCLUDE_GLOBALS:
            globals_dict = {k: v for k, v in frame.f_globals.items()
                           if not k.startswith("__") and k != "catch"}
            if globals_dict:
                glob_items = list(globals_dict.items())[:MAX_LOCAL_VARS]
                glob_lines = []
                for name, value in glob_items:
                    try:
                        val_str = repr(value)
                        if len(val_str) > 100:
                            val_str = val_str[:97] + "..."
                        glob_lines.append(f"    {name} = {val_str}")
                    except:
                        glob_lines.append(f"    {name} = <error>")

                glob_header = "🌍 Глобальные переменные:"
                if use_color:
                    lines.append(f"\n{Colors.CYAN}{glob_header}{Colors.RESET}\n" + "\n".join(glob_lines))
                else:
                    lines.append(f"\n{glob_header}\n" + "\n".join(glob_lines))
    else:
        # Спецобработка для BrokenProcessPool и других случаев без стека
        if exc_name == "BrokenProcessPool":
            lines.append("  💀 Процесс-воркер был уничтожен (segfault/kill/OOM)")
        else:
            lines.append("  (нет стека вызовов)")

    lines.append("")
    return "\n".join(lines)

def _print_and_log(exc_type, exc_value, exc_tb):
    formatted = format_exception(exc_type, exc_value, exc_tb)
    if formatted:
        print(formatted, file=sys.stderr)
        tb_str = "".join(traceback.format_tb(exc_tb)) if exc_tb else "(no traceback)"
        logger.error("%s: %s\n%s", exc_type.__name__, str(exc_value), tb_str)

# ============================================================================
# ПЕРЕХВАТЧИКИ
# ============================================================================

_enabled = True
_original_excepthook = sys.excepthook
_original_threading_excepthook = getattr(threading, 'excepthook', None)

def enable():
    global _enabled
    _enabled = True
    _install_hooks()

def disable():
    global _enabled
    _enabled = False
    _uninstall_hooks()

def is_enabled() -> bool:
    return _enabled

def _custom_excepthook(exc_type, exc_value, exc_tb):
    if _enabled:
        _print_and_log(exc_type, exc_value, exc_tb)
    if _original_excepthook:
        _original_excepthook(exc_type, exc_value, exc_tb)

def _custom_threading_excepthook(args):
    if _enabled:
        _print_and_log(args.exc_type, args.exc_value, args.exc_traceback)
    if _original_threading_excepthook:
        _original_threading_excepthook(args)

def _install_hooks():
    sys.excepthook = _custom_excepthook
    if hasattr(threading, 'excepthook'):
        threading.excepthook = _custom_threading_excepthook

def _uninstall_hooks():
    sys.excepthook = _original_excepthook
    if _original_threading_excepthook and hasattr(threading, 'excepthook'):
        threading.excepthook = _original_threading_excepthook

# KeyboardInterrupt
def _handle_keyboard_interrupt(signum, frame):
    if _enabled:
        msg = "⚡ Прервано пользователем (Ctrl+C)"
        if Colors.is_terminal():
            print(f"\n{Colors.YELLOW}{msg}{Colors.RESET}", file=sys.stderr)
        else:
            print(f"\n{msg}", file=sys.stderr)
    raise KeyboardInterrupt()

try:
    signal.signal(signal.SIGINT, _handle_keyboard_interrupt)
except (ValueError, OSError):
    pass

# Warnings
def _warning_handler(message, category, filename, lineno, file=None, line=None):
    if _enabled:
        use_color = Colors.is_terminal()
        exc_name = category.__name__
        exc_msg = str(message)
        translated = translate_error(exc_name, exc_msg)

        header = f"⚠ ПРЕДУПРЕЖДЕНИЕ: {translated}"
        if use_color:
            print(f"\n{Colors.YELLOW}{Colors.BOLD}{header}{Colors.RESET}", file=sys.stderr)
        else:
            print(f"\n{header}", file=sys.stderr)

        print(f"  📍 {filename}:{lineno}", file=sys.stderr)
        if line:
            print(f"      → {line.strip()}", file=sys.stderr)
        print("", file=sys.stderr)

        logger.warning("%s: %s at %s:%s", exc_name, exc_msg, filename, lineno)

warnings.showwarning = _warning_handler

# ============================================================================
# MULTIPROCESSING — ИНИЦИАЛИЗАТОР ДЛЯ ВОРКЕРОВ
# ============================================================================

def _worker_initializer():
    """Устанавливает хуки внутри каждого воркера multiprocessing."""
    sys.excepthook = _custom_excepthook
    if hasattr(threading, 'excepthook'):
        threading.excepthook = _custom_threading_excepthook

# Патч ProcessPoolExecutor для добавления initializer
_original_process_pool_init = ProcessPoolExecutor.__init__

def _patched_process_pool_init(self, *args, **kwargs):
    original_initializer = kwargs.get('initializer')
    original_initargs = kwargs.get('initargs', ())

    def _combined_initializer(*init_args):
        _worker_initializer()
        if original_initializer:
            original_initializer(*init_args)

    kwargs['initializer'] = _combined_initializer
    kwargs['initargs'] = original_initargs

    _original_process_pool_init(self, *args, **kwargs)

ProcessPoolExecutor.__init__ = _patched_process_pool_init

# ============================================================================
# CONCURRENT.FUTURES — CALLBACK НА РЕЗУЛЬТАТ
# ============================================================================

_original_submit_thread = ThreadPoolExecutor.submit
_original_submit_process = ProcessPoolExecutor.submit

def _check_future_exception(fut):
    """Callback для проверки исключений в futures."""
    try:
        fut.result()
    except asyncio.CancelledError:
        # Игнорируем отмену задачи
        return
    except BaseException as e:
        if _enabled and not getattr(e, "_smart_caught", False):
            exc_type = type(e)
            exc_value = e
            exc_tb = e.__traceback__
            if exc_tb:
                _print_and_log(exc_type, exc_value, exc_tb)
            else:
                # Fallback без стека
                use_color = Colors.is_terminal()
                translated = translate_error(exc_type.__name__, str(exc_value))

                if exc_type.__name__ == "BrokenProcessPool":
                    header = f"⚠ ОШИБКА: {translated}\n  💀 Процесс-воркер уничтожен"
                else:
                    header = f"⚠ ОШИБКА В FUTURES: {translated}"

                if use_color:
                    print(f"\n{Colors.RED}{Colors.BOLD}{header}{Colors.RESET}", file=sys.stderr)
                else:
                    print(f"\n{header}", file=sys.stderr)
                logger.error("%s: %s (no traceback)", exc_type.__name__, str(exc_value))

def _patched_submit_thread(self, fn, *args, **kwargs):
    future = _original_submit_thread(self, fn, *args, **kwargs)
    future.add_done_callback(_check_future_exception)
    return future

def _patched_submit_process(self, fn, *args, **kwargs):
    future = _original_submit_process(self, fn, *args, **kwargs)
    future.add_done_callback(_check_future_exception)
    return future

ThreadPoolExecutor.submit = _patched_submit_thread
ProcessPoolExecutor.submit = _patched_submit_process

# ============================================================================
# ASYNCIO SAFE RUN
# ============================================================================

async def safe_run(coro, return_exceptions: bool = False):
    """Асинхронная обертка для перехвата ошибок в корутине."""
    try:
        return await coro
    except asyncio.CancelledError:
        raise
    except BaseException as e:
        if _enabled:
            exc_type = type(e)
            exc_value = e
            exc_tb = e.__traceback__
            if exc_tb:
                _print_and_log(exc_type, exc_value, exc_tb)
            else:
                use_color = Colors.is_terminal()
                translated = translate_error(exc_type.__name__, str(exc_value))
                header = f"⚠ ОШИБКА В ASYNC: {translated}"
                if use_color:
                    print(f"\n{Colors.RED}{Colors.BOLD}{header}{Colors.RESET}", file=sys.stderr)
                else:
                    print(f"\n{header}", file=sys.stderr)
                logger.error("%s: %s (no traceback)", exc_type.__name__, str(exc_value))
        if return_exceptions:
            return e
        raise
def run_safe(coro, return_exceptions: bool = False):
    """Запускает корутину безопасно. Создаёт loop или использует существующий."""
    async def _runner():
        return await safe_run(coro, return_exceptions)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Внутри running loop — создаём task и ждём
        import concurrent
        future = asyncio.ensure_future(_runner(), loop=loop)
        # Нельзя блокирующе ждать внутри running loop, возвращаем future
        return future
    else:
        # Нет loop — создаём новый
        return asyncio.run(_runner())

# ============================================================================
# ДЕКОРАТОРЫ
# ============================================================================

def catch_errors(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except BaseException as e:
            if _enabled:
                e._smart_caught = True  # type: ignore
                exc_type = type(e)
                exc_value = e
                exc_tb = e.__traceback__
                if exc_tb:
                    _print_and_log(exc_type, exc_value, exc_tb)
                else:
                    use_color = Colors.is_terminal()
                    translated = translate_error(exc_type.__name__, str(exc_value))
                    header = f"⚠ ОШИБКА: {translated}"
                    if use_color:
                        print(f"\n{Colors.RED}{Colors.BOLD}{header}{Colors.RESET}", file=sys.stderr)
                    else:
                        print(f"\n{header}", file=sys.stderr)
                    logger.error("%s: %s (no traceback)", exc_type.__name__, str(exc_value))
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
            if _enabled:
                e._smart_caught = True  # type: ignore
                exc_type = type(e)
                exc_value = e
                exc_tb = e.__traceback__
                if exc_tb:
                    _print_and_log(exc_type, exc_value, exc_tb)
                else:
                    use_color = Colors.is_terminal()
                    translated = translate_error(exc_type.__name__, str(exc_value))
                    header = f"⚠ ОШИБКА: {translated}"
                    if use_color:
                        print(f"\n{Colors.RED}{Colors.BOLD}{header}{Colors.RESET}", file=sys.stderr)
                    else:
                        print(f"\n{header}", file=sys.stderr)
                    logger.error("%s: %s (no traceback)", exc_type.__name__, str(exc_value))
            raise
    return wrapper

# ============================================================================
# ПРИВЕТСТВИЕ
# ============================================================================

def _show_welcome():
    if Colors.is_terminal():
        print(f"\n{Colors.GREEN}{Colors.BOLD}🛡️  Catch Error Handler v6.2 [FINAL]{Colors.RESET}")
        print(f"{Colors.CYAN}   Перехват: {'ON' if _enabled else 'OFF'} | Лог: {LOG_FILE} | Python {sys.version.split()[0]}{Colors.RESET}")
        print(f"{Colors.YELLOW}   ⚠ Импорт должен быть ПЕРВЫМ в проекте!{Colors.RESET}\n")
    else:
        print(f"\n🛡️  Catch Error Handler v6.2 [FINAL]")
        print(f"   Перехват: {'ON' if _enabled else 'OFF'} | Лог: {LOG_FILE} | Python {sys.version.split()[0]}")
        print(f"   ⚠ Импорт должен быть ПЕРВЫМ в проекте!\n")

_show_welcome()
_install_hooks()