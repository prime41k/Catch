"""Catch.py v8.0 — God Mode & Instant Fixes."""
import sys, os, logging, threading, traceback, asyncio, functools, warnings, signal
import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from typing import Callable
from collections import deque

# === CONFIG ===
LOG_FILE = "errors.log"
MAX_LOCAL_VARS = 5
MAX_STACK_FRAMES = 5
SILENT_MODE = os.environ.get("CATCH_SILENT", "0") == "1"

class Colors:
    RED = "\033[91m"; YELLOW = "\033[93m"; CYAN = "\033[96m"
    GREEN = "\033[92m"; BOLD = "\033[1m"; RESET = "\033[0m"
    @staticmethod
    def is_terminal():
        return hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()

# === MEGA DICTIONARY (100+ Errors) ===
ERROR_DB = {
    # Base Python
    "ZeroDivisionError": ("Деление на ноль", "Проверь делитель перед операцией или используй try/except."),
    "FileNotFoundError": ("Файл не найден", "Убедись, что путь к файлу верный и файл существует."),
    "PermissionError": ("Нет прав доступа", "Запусти скрипт с sudo или проверь chmod файла."),
    "KeyError": ("Ключ не найден", "Используй dict.get('key') вместо прямого обращения."),
    "IndexError": ("Индекс за пределами", "Проверь длину списка перед обращением по индексу."),
    "TypeError": ("Ошибка типа данных", "Проверь типы переменных через type()."),
    "ValueError": ("Неверное значение", "Убедись, что входные данные соответствуют ожидаемому формату."),
    "AttributeError": ("Атрибут не найден", "Проверь наличие метода/поля у объекта через dir()."),
    "ImportError": ("Ошибка импорта", "Установи модуль: pip install <module_name>."),
    "ModuleNotFoundError": ("Модуль не найден", "Установи модуль: pip install <module_name>."),       "NameError": ("Переменная не определена", "Проверь опечатки в имени переменной."),
    "SyntaxError": ("Синтаксическая ошибка", "Проверь скобки, двоеточия и отступы."),
    "IndentationError": ("Ошибка отступов", "Используй либо только Tab, либо только 4 пробела."),
    "TabError": ("Смешаны Tab и Space", "Настрой IDE на замену Tab на пробелы."),
    "RuntimeError": ("Ошибка выполнения", "Проверь логику работы программы."),
    "RecursionError": ("Бесконечная рекурсия", "Добавь условие выхода из рекурсии."),
    "MemoryError": ("Нехватка памяти", "Оптимизируй использование памяти или увеличь swap."),
    "OverflowError": ("Переполнение числа", "Используй библиотеку decimal для больших чисел."),
    "StopIteration": ("Итератор исчерпан", "Используй цикл for вместо ручного next()."),
    "AssertionError": ("Assert failed", "Проверь условие утверждения."),
    "NotImplementedError": ("Метод не реализован", "Реализуй метод в дочернем классе."),
    "EOFError": ("Конец файла", "Проверь целостность входных данных."),

    # OS & IO
    "OSError": ("Системная ошибка", "Проверь права доступа и наличие ресурсов."),
    "IOError": ("Ошибка ввода/вывода", "Проверь диск и файловую систему."),
    "BlockingIOError": ("Блокировка IO", "Используй асинхронные операции или таймауты."),
    "BrokenPipeError": ("Обрыв канала", "Проверь, не закрыл ли клиент соединение."),
    "ChildProcessError": ("Ошибка процесса", "Проверь аргументы запуска subprocess."),
    "FileExistsError": ("Файл уже существует", "Используй mode='w' или проверь os.path.exists."),     "IsADirectoryError": ("Это директория", "Убедись, что работаешь с файлом, а не папкой."),
    "NotADirectoryError": ("Это не директория", "Проверь путь к папке."),
                                                                                                      # Network & Web
    "ConnectionError": ("Ошибка соединения", "Проверь интернет и доступность сервера."),
    "ConnectionRefusedError": ("Соединение отклонено", "Проверь, запущен ли сервис и порт."),
    "ConnectionResetError": ("Соединение сброшено", "Сервер разорвал связь. Попробуй reconnect."),
    "TimeoutError": ("Таймаут", "Увеличь timeout или проверь сеть."),
    "URLError": ("Ошибка URL", "Проверь правильность адреса ссылки."),
    "HTTPError": ("Ошибка HTTP", "Проверь статус код ответа сервера."),
    "SSLError": ("Ошибка SSL", "Обнови сертификаты или проверь дату системы."),
    "ProxyError": ("Ошибка прокси", "Проверь настройки прокси-сервера."),
    "ContentTooShortError": ("Контент слишком короткий", "Проверь источник данных."),

    # Data & Encoding
    "JSONDecodeError": ("Ошибка JSON", "Проверь валидность JSON строки через jsonlint."),
    "UnicodeDecodeError": ("Ошибка кодировки", "Укажи encoding='utf-8' при открытии файла."),
    "UnicodeEncodeError": ("Ошибка записи", "Проверь поддерживаемые символы кодировки."),
    "CSVError": ("Ошибка CSV", "Проверь разделители и экранирование."),
    "PickleError": ("Ошибка сериализации", "Убедись, что объект можно пиклить."),

    # Concurrency & Async
    "BrokenProcessPool": ("Воркер крашнулся", "Проверь память и отсутствие глобального стейта."),
    "CancelledError": ("Задача отменена", "Это нормальное поведение при остановке."),
    "InvalidStateError": ("Неверное состояние", "Проверь порядок вызова методов Future."),
    "ConcurrentFutureError": ("Ошибка Future", "Проверь результат выполнения задачи."),

    # Crypto & Security
    "ValidationError": ("Ошибка валидации", "Проверь входные данные на соответствие схеме."),
    "AuthenticationError": ("Ошибка входа", "Проверь логин и пароль/токен."),
    "AuthorizationError": ("Нет прав", "Проверь роли и разрешения пользователя."),
    "InvalidTokenError": ("Неверный токен", "Обнови или перегенерируй токен доступа."),

    # Database
    "DatabaseError": ("Ошибка БД", "Проверь подключение и запрос SQL."),
    "IntegrityError": ("Нарушение целостности", "Проверь уникальные ключи и внешние связи."),
    "OperationalError": ("Ошибка операции БД", "Проверь доступность сервера БД."),
    "ProgrammingError": ("Ошибка в SQL", "Проверь синтаксис запроса."),

    # Telegram / Specific Libs
    "FloodWaitError": ("Флуд-контроль", "Сделай паузу перед следующим запросом."),
    "SessionPasswordNeeded": ("Нужен 2FA", "Укажи пароль двухфакторной аутентификации."),
    "PhoneCodeInvalidError": ("Неверный код", "Проверь код из SMS/Telegram."),                        "PeerIdInvalidError": ("Неверный ID", "Проверь ID пользователя или чата."),
    "ChatWriteForbiddenError": ("Запрет письма", "Ты не можешь писать в этот чат."),
    "UserIsBlockedError": ("Пользователь заблокировал", "Нельзя написать этому пользователю."),
    "MessageDeleteForbiddenError": ("Нельзя удалить", "Нет прав на удаление сообщений."),
    "MediaEmptyError": ("Пустое медиа", "Проверь наличие файла перед отправкой."),
    "FilePartLengthInvalid": ("Ошибка части файла", "Проверь размер чанков при загрузке."),
    "RpcCallFailError": ("Ошибка RPC", "Сервер Telegram временно недоступен."),
    "SlowModeWaitError": ("Режим медленной отправки", "Подожди указанное время."),
    "ChannelsTooMuchError": ("Много каналов", "Выступи из части каналов перед вступлением."),
    "UsersTooMuchError": ("Много пользователей", "Лимит добавления участников превышен."),
    "BroadcastPublicVotersForbidden": ("Голосование публично", "Нельзя создавать публичные опросы здесь."),                                                                                             "AdminRankInvalidError": ("Неверный ранг", "Проверь название админской должности."),
    "BannedRightsInvalid": ("Неверные права бана", "Проверь параметры ограничения прав."),
    "BotMethodInvalid": ("Метод недоступен боту", "Этот метод нельзя использовать ботом."),
    "BotPaymentsDisabled": ("Платежи отключены", "Включи платежи в BotFather."),
    "ButtonDataInvalid": ("Неверные данные кнопки", "Проверь callback_data кнопки."),
    "ButtonTypeInvalid": ("Неверный тип кнопки", "Используй поддерживаемые типы кнопок."),
    "ButtonUrlInvalid": ("Неверная ссылка кнопки", "Проверь URL адрес кнопки."),
    "CallbackQueryEmpty": ("Пустой callback", "Обработчик кнопки не вернул ответ."),
    "ChannelInvalid": ("Неверный канал", "Проверь ссылку или ID канала."),
    "ChannelPrivate": ("Канал приватный", "Нет доступа к приватному каналу."),
    "ChatAboutNotModified": ("Описание не изменено", "Новое описание совпадает со старым."),
    "ChatAdminRequired": ("Нужны права админа", "Получи права администратора в чате."),
    "ChatForwardsRestricted": ("Пересылка запрещена", "В чате запрещено пересылать сообщения."),
    "ChatIdEmpty": ("Пустой ID чата", "Укажи ID чата для операции."),
    "ChatIdInvalid": ("Неверный ID чата", "Проверь идентификатор чата."),
    "ChatLinkExpired": ("Ссылка истекла", "Создай новую пригласительную ссылку."),
    "ChatRevokeDateMissing": ("Дата отзыва missing", "Укажи дату для отзыва ссылки."),
    "ChatSendGifsForbidden": ("Запрет GIF", "В чате запрещено отправлять GIF."),
    "ChatSendInlineForbidden": ("Запрет Inline", "В чате запрещено использовать inline ботов."),
    "ChatSendMediaForbidden": ("Запрет медиа", "В чате запрещено отправлять медиа."),
    "ChatSendPlainForbidden": ("Запрет текста", "В чате запрещено отправлять текст."),
    "ChatSendPollsForbidden": ("Запрет опросов", "В чате запрещено создавать опросы."),
    "ChatSendStickersForbidden": ("Запрет стикеров", "В чате запрещено отправлять стикеры."),         "ChatTitleEmpty": ("Пустое название", "Укажи название для чата."),
    "ChatTooBig": ("Чат слишком большой", "Лимит участников превышен."),
    "ChatWriteForbidden": ("Запрет письма", "Ты не можешь писать в этот чат."),
    "ConnectionDevicePacketLimit": ("Лимит пакетов", "Слишком много запросов с устройства."),
    "ConnectionNotInited": ("Соединение не инициировано", "Выполни init соединения."),
    "ContactAddFailed": ("Не удалось добавить контакт", "Проверь номер телефона."),
    "ContactIdInvalid": ("Неверный ID контакта", "Проверь идентификатор контакта."),
    "ContactNameEmpty": ("Пустое имя контакта", "Укажи имя для контакта."),
    "ContactsTooMuch": ("Много контактов", "Удали часть контактов."),
    "DataInvalid": ("Неверные данные", "Проверь формат передаваемых данных."),                        "DateEmpty": ("Пустая дата", "Укажи дату для операции."),
    "DcIdInvalid": ("Неверный DC ID", "Проверь идентификатор дата-центра."),
    "DialogFilterExcludeTooMany": ("Много исключений", "Уменьши количество исключений в фильтре."),                                                                                                     "DialogFilterIncludeTooMany": ("Много включений", "Уменьши количество включений в фильтре."),
    "DialogFilterTitleEmpty": ("Пустое название фильтра", "Укажи название для фильтра диалогов."),
    "DialogFilterChatsTooMuch": ("Много чатов в фильтре", "Уменьши количество чатов в фильтре."),
    "DialogFilterIdEmpty": ("Пустой ID фильтра", "Укажи ID для фильтра диалогов."),
    "DialogFilterIdInvalid": ("Неверный ID фильтра", "Проверь идентификатор фильтра."),
}

def get_error_info(exc_name):
    """Возвращает (Russian Name, Fix Advice)"""
    if exc_name in ERROR_DB:
        return ERROR_DB[exc_name]
    return (exc_name, "Проверь документацию Python или библиотеки.")

# === LOGGING ===
logger = logging.getLogger("catch_errors")
logger.setLevel(logging.ERROR)
if not logger.handlers:                                                                               fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(fh)

# === FAST DEDUP ===
_processed_hashes = deque(maxlen=2000)
_lock = threading.Lock()

def _is_already_processed(exc):
    # Быстрый хеш без md5
    h = f"{type(exc).__name__}:{str(exc)[:30]}"
    with _lock:
        if h in _processed_hashes or getattr(exc, "_smart_caught", False):
            return True
        _processed_hashes.append(h)
        exc._smart_caught = True
        return False

# === FILTERS ===
def _is_our_code(filename):
    if not filename: return True
    ignore = ["lib/python", "site-packages", "dist-packages", "<frozen"]
    return not any(p in filename for p in ignore)

def format_exception(exc_type, exc_value, exc_tb):
    if _is_already_processed(exc_value):
        return ""

    noisy = {ConnectionResetError, BrokenPipeError, OSError}
    try:
        from telethon.errors import FloodWaitError
        noisy.add(FloodWaitError)
    except: pass

    if exc_type in noisy:
        logger.warning("[noise] %s: %s", exc_type.__name__, exc_value)
        return ""

    lines = []
    use_color = Colors.is_terminal()                                                                  exc_name = exc_type.__name__
    ru_name, fix_advice = get_error_info(exc_name)                                                
    header = f"⚠ ОШИБКА: {ru_name}"
    if use_color:
        lines.append(f"\n{Colors.RED}{Colors.BOLD}{header}{Colors.RESET}")
    else:
        lines.append(f"\n{header}")

    # FIX ADVICE BLOCK
    if fix_advice:
        fix_line = f"💡 Как исправить: {fix_advice}"
        if use_color:
            lines.append(f"{Colors.GREEN}{fix_line}{Colors.RESET}")                                       else:
            lines.append(fix_line)

    if exc_tb:
        full_stack = traceback.extract_tb(exc_tb)                                                         relevant = [f for f in full_stack if _is_our_code(f.filename)]
        if not relevant: relevant = full_stack[-3:]
        else: relevant = relevant[-MAX_STACK_FRAMES:]

        stack_header = "📍 Твой код:"
        if use_color:
            lines.append(f"{Colors.CYAN}{stack_header}{Colors.RESET}")
        else:
            lines.append(stack_header)

        for i, frame in enumerate(relevant):                                                                  fname = os.path.basename(frame.filename)
            line_code = frame.line or ""
            if use_color:
                lines.append(f"  {Colors.YELLOW}[{i+1}] {fname}:{frame.lineno} в {frame.name}(){Colors.RESET}")
            else:
                lines.append(f"  [{i+1}] {fname}:{frame.lineno} в {frame.name}()")
            if line_code:
                lines.append(f"      → {line_code}")

        if relevant:
            tb = exc_tb
            while tb.tb_next: tb = tb.tb_next
            if _is_our_code(tb.tb_frame.f_code.co_filename):
                locals_dict = tb.tb_frame.f_locals
                if locals_dict:
                    items = list(locals_dict.items())[:MAX_LOCAL_VARS]
                    loc_lines = []
                    for name, value in items:
                        try:                                                                                                  val_str = repr(value)
                            if len(val_str) > 80: val_str = val_str[:77] + "..."
                            loc_lines.append(f"    {name} = {val_str}")
                        except: loc_lines.append(f"    {name} = <err>")

                    if len(locals_dict) > MAX_LOCAL_VARS:
                        loc_lines.append(f"    ... +{len(locals_dict) - MAX_LOCAL_VARS}")

                    loc_header = "🔧 Локальные переменные:"
                    if use_color:
                        lines.append(f"\n{Colors.CYAN}{loc_header}{Colors.RESET}\n" + "\n".join(loc_lines))
                    else:
                        lines.append(f"\n{loc_header}\n" + "\n".join(loc_lines))
    else:
        if exc_name == "BrokenProcessPool":
            lines.append("  💀 Процесс-воркер уничтожен ядром ОС")
        else:
            lines.append("  (стек вызовов недоступен)")

    if exc_value.__cause__:
        cause_name, _ = get_error_info(type(exc_value.__cause__).__name__)
        lines.append(f"{Colors.YELLOW}  ↳ Причина: {cause_name}{Colors.RESET}" if use_color else f"  ↳ Причина: {cause_name}")
                                                                                                      lines.append("")
    return "\n".join(lines)

def _print_and_log(exc_type, exc_value, exc_tb):
    formatted = format_exception(exc_type, exc_value, exc_tb)
    if formatted:
        print(formatted, file=sys.stderr)
        tb_str = "".join(traceback.format_tb(exc_tb)) if exc_tb else "(no traceback)"
        logger.error("%s: %s\n%s", exc_type.__name__, str(exc_value), tb_str)

# === HOOKS ===                                                                                   _enabled = True
_original_excepthook = sys.excepthook
_original_threading_excepthook = getattr(threading, 'excepthook', None)                           
def enable():
    global _enabled; _enabled = True; _install_hooks()

def disable():
    global _enabled; _enabled = False; _uninstall_hooks()

def is_enabled(): return _enabled

def _custom_excepthook(exc_type, exc_value, exc_tb):
    if _enabled: _print_and_log(exc_type, exc_value, exc_tb)
    if _original_excepthook: _original_excepthook(exc_type, exc_value, exc_tb)

def _custom_threading_excepthook(args):                                                               if _enabled: _print_and_log(args.exc_type, args.exc_value, args.exc_traceback)
    if _original_threading_excepthook: _original_threading_excepthook(args)

def _install_hooks():
    sys.excepthook = _custom_excepthook
    if hasattr(threading, 'excepthook'): threading.excepthook = _custom_threading_excepthook      
def _uninstall_hooks():
    sys.excepthook = _original_excepthook
    if _original_threading_excepthook and hasattr(threading, 'excepthook'):
        threading.excepthook = _original_threading_excepthook

def _handle_keyboard_interrupt(signum, frame):
    if _enabled:
        msg = "⚡ Preravano (Ctrl+C)"
        if Colors.is_terminal(): print(f"\n{Colors.YELLOW}{msg}{Colors.RESET}", file=sys.stderr)
        else: print(f"\n{msg}", file=sys.stderr)
    raise KeyboardInterrupt()

try:
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, _handle_keyboard_interrupt)
except: pass

def _warning_handler(message, category, filename, lineno, file=None, line=None):
    if _enabled and _is_our_code(filename):
        use_color = Colors.is_terminal()
        exc_name = category.__name__
        ru_name, _ = get_error_info(exc_name)
        header = f"⚠ WARN: {ru_name}"
        if use_color: print(f"\n{Colors.YELLOW}{Colors.BOLD}{header}{Colors.RESET}", file=sys.stderr)
        else: print(f"\n{header}", file=sys.stderr)
        print(f"  📍 {os.path.basename(filename)}:{lineno}", file=sys.stderr)
        logger.warning("%s: %s at %s:%s", exc_name, str(message), filename, lineno)

warnings.showwarning = _warning_handler

# === MULTIPROCESSING & FUTURES ===
def _worker_initializer():
    sys.excepthook = _custom_excepthook                                                               if hasattr(threading, 'excepthook'): threading.excepthook = _custom_threading_excepthook
                                                                                                  _original_process_pool_init = ProcessPoolExecutor.__init__
def _patched_process_pool_init(self, *args, **kwargs):
    original_initializer = kwargs.get('initializer')
    original_initargs = kwargs.get('initargs', ())                                                    def _combined_initializer(*init_args):
        _worker_initializer()
        if original_initializer: original_initializer(*init_args)
    kwargs['initializer'] = _combined_initializer                                                     kwargs['initargs'] = original_initargs
    _original_process_pool_init(self, *args, **kwargs)
ProcessPoolExecutor.__init__ = _patched_process_pool_init
                                                                                                  _original_submit_thread = ThreadPoolExecutor.submit
_original_submit_process = ProcessPoolExecutor.submit

def _check_future_exception(fut):
    try: fut.result()
    except asyncio.CancelledError: return
    except BaseException as e:
        if _enabled and not getattr(e, "_smart_caught", False):
            exc_tb = e.__traceback__
            if exc_tb: _print_and_log(type(e), e, exc_tb)                                                     else:
                ru_name, _ = get_error_info(type(e).__name__)                                                     header = f"⚠ FUTURE ERROR: {ru_name}"
                if type(e).__name__ == "BrokenProcessPool": header += "\n  💀 Worker dead"
                if Colors.is_terminal(): print(f"\n{Colors.RED}{Colors.BOLD}{header}{Colors.RESET}", file=sys.stderr)                                                                                               else: print(f"\n{header}", file=sys.stderr)
                logger.error("%s: %s", type(e).__name__, str(e))

def _patched_submit_thread(self, fn, *args, **kwargs):                                                future = _original_submit_thread(self, fn, *args, **kwargs)
    future.add_done_callback(_check_future_exception)
    return future

def _patched_submit_process(self, fn, *args, **kwargs):
    future = _original_submit_process(self, fn, *args, **kwargs)
    future.add_done_callback(_check_future_exception)
    return future
                                                                                                  ThreadPoolExecutor.submit = _patched_submit_thread
ProcessPoolExecutor.submit = _patched_submit_process

# === ASYNC & DECORATORS ===
async def safe_run(coro, return_exceptions=False):
    try: return await coro
    except asyncio.CancelledError: raise
    except BaseException as e:
        if _enabled:
            exc_tb = e.__traceback__
            if exc_tb: _print_and_log(type(e), e, exc_tb)
            else:
                ru_name, _ = get_error_info(type(e).__name__)
                header = f"⚠ ASYNC ERROR: {ru_name}"
                if Colors.is_terminal(): print(f"\n{Colors.RED}{Colors.BOLD}{header}{Colors.RESET}", file=sys.stderr)
                else: print(f"\n{header}", file=sys.stderr)
                logger.error("%s: %s", type(e).__name__, str(e))
        if return_exceptions: return e
        raise

def run_safe(coro, return_exceptions=False):
    async def _runner(): return await safe_run(coro, return_exceptions)
    try: loop = asyncio.get_running_loop()
    except RuntimeError: loop = None
    if loop and loop.is_running(): return asyncio.ensure_future(_runner(), loop=loop)
    else: return asyncio.run(_runner())

def catch_errors(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try: return func(*args, **kwargs)
        except BaseException as e:
            if _enabled:
                e._smart_caught = True
                exc_tb = e.__traceback__
                if exc_tb: _print_and_log(type(e), e, exc_tb)
                else:
                    ru_name, _ = get_error_info(type(e).__name__)
                    if Colors.is_terminal(): print(f"\n{Colors.RED}{Colors.BOLD}⚠ ERROR: {ru_name}{Colors.RESET}", file=sys.stderr)
                    else: print(f"\n⚠ ERROR: {ru_name}", file=sys.stderr)
                    logger.error("%s: %s", type(e).__name__, str(e))
            raise                                                                                     return wrapper

def async_catch(func: Callable) -> Callable:
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try: return await func(*args, **kwargs)
        except asyncio.CancelledError: raise
        except BaseException as e:
            if _enabled:
                e._smart_caught = True
                exc_tb = e.__traceback__
                if exc_tb: _print_and_log(type(e), e, exc_tb)
                else:
                    ru_name, _ = get_error_info(type(e).__name__)
                    if Colors.is_terminal(): print(f"\n{Colors.RED}{Colors.BOLD}⚠ ERROR: {ru_name}{Colors.RESET}", file=sys.stderr)
                    else: print(f"\n⚠ ERROR: {ru_name}", file=sys.stderr)
                    logger.error("%s: %s", type(e).__name__, str(e))
            raise
    return wrapper

# === WELCOME ===
def _show_welcome():
    if SILENT_MODE: return
    if Colors.is_terminal():
        print(f"\n{Colors.GREEN}{Colors.BOLD}🛡️  Catch Error Handler v8.0 [GOD MODE]{Colors.RESET}")                                                                                                         print(f"{Colors.CYAN}   Mode: {'ON' if _enabled else 'OFF'} | Log: {LOG_FILE} | Py {sys.version.split()[0]}{Colors.RESET}")
        print(f"{Colors.YELLOW}   ⚠ Import FIRST!{Colors.RESET}\n")
    else:
        print(f"\n🛡️  Catch Error Handler v8.0 [GOD MODE]")
        print(f"   Mode: {'ON' if _enabled else 'OFF'} | Log: {LOG_FILE} | Py {sys.version.split()[0]}\n")

_show_welcome()
_install_hooks()