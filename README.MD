Catch.py v9.5 — обработчик ошибок который не бесит

короче это штука которая ловит все исключения в питоне и выводит их нормально а не тем уродским трейсбеком на 200 строк где половина из site-packages. написал потому что задолбался смотреть в простыню когда где-то отвалилась телега или база.

что умеет

ловит всё — sys.excepthook, threading.excepthook, asyncio таски, future из пулов, ворнинги, ctrl+c. всё что летит в stderr перехватывается и выводится по-человечески.

красиво красит в терминале — красным ошибка, зелёным фикс, жёлтым твой код, цианом локальные переменные. если stderr не в терминал — цвета отключаются сами, в лог файл не летит мусор с ANSI escape.

словарь на 1625 ошибок с подсказками на русском. когда падает KeyError он не просто пишет KeyError а говорит ключ не найден и советует dict.get(). для телеграма вообще огромная база — FloodWait, PeerIdInvalid и прочая хрень.

контекст для трейсинга — trace_id, user_id, request_id через contextvars. в каждом сообщении видно какой запрос упал и у кого. работает и в тредах и в asyncio.

rate limiter — не больше 50 ошибок в секунду в лог. если у тебя цикл который спамит исключениями диск не умрёт.

safe repr — локальные переменные в трейсбеке режутся через пул потоков с таймаутом. если у тебя в locals сокет или коннект к базе который в repr виснет — процесс не повиснет, просто напишет <socket>.

экспорт в sentry и opentelemetry — одна строка и все ошибки летят в твой мониторинг.

статистика — get_stats() возвращает сколько поймано, сколько заглушено как шум, сколько отсечено лимитом. reset_stats() для долгих процессов.

как ставить

кидаешь Catch.py и error_db.json в проект. всё. никаких pip install.

import Catch в самом начале главного файла. важно — первым, иначе хуки не подхватят ошибки из других модулей которые импортируются до.

базовое использование

ничего делать не надо. импортировал и забыл. все необработанные исключения теперь красивые.

если используешь пулы

Catch.enable_pools()

вызывать после импорта но до создания ProcessPoolExecutor или ThreadPoolExecutor. иначе не подхватит.

если используешь asyncio

import asyncio
loop = asyncio.new_event_loop()
Catch.enable_asyncio(loop)
asyncio.set_event_loop(loop)

важно — вызывать до asyncio.run или до создания тасок. если loop уже запущен будет warning и существующие таски не подхватятся.

контекст для запроса

в начале обработки запроса

Catch.set_context(trace_id=req.id, user_id=user.id, request_id=req.request_id)

теперь в каждой ошибке будет видно [trace=xxx user=42 req=yyy]. работает через contextvars так что в asyncio каждый запрос имеет свой контекст и они не мешаются.

sentry

Catch.init_exports(sentry_dsn=https://xxx@sentry.io/123)

всё. теперь каждая ошибка летит в sentry с полным стеком и контекстом.

opentelemetry

Catch.init_exports(otel=True)

пишет в текущий span через record_exception.

декораторы

если хочешь ловить ошибки внутри функции но не прерывать выполнение

@Catch.catch_errors
def my_func():
    1/0

ошибка залогится но пробросится дальше. если нужно вернуть ошибку а не пробрасывать

result = await Catch.safe_run(some_coro(), return_exceptions=True)

если some_coro упал — result будет исключением, не краш.

ручная пометка

если ты сам поймал ошибку и обработал но не хочешь чтобы catch её снова логировал

try:
    risky()
except Exception as e:
    Catch.mark_as_handled(e)
    handle_somehow()

шумные ошибки

ConnectionResetError, BrokenPipeError, OSError и FloodWaitError от телеги по умолчанию игнорируются — только warning в лог. если хочешь добавить свои

Catch.suppress_noise([MyNoisyError, AnotherOne])

валидация типов — если передашь не BaseException subclass кинет TypeError.

перенаправление вывода

по умолчанию всё летит в stderr. если хочешь в файл или syslog

f = open(my_errors.log, a)
Catch.set_output(f)

старый стрим закроется автоматически если это не stderr/stdout.

закрыть вручную

Catch.close_output()

последняя ошибка

в любом месте можно получить последнее исключение текущего контекста

err = Catch.get_last_error()

работает и в тредах и в asyncio потому что через contextvars.

статистика

stats = Catch.get_stats()
print(stats)

вернёт dict с ключами caught noisy rate_limited exported warn_rate_limited.

сбросить

Catch.reset_stats()

ctrl+c

когда жмёшь ctrl+c выводится жёлтое сообщение и потом стандартный KeyboardInterrupt. стек не теряется.

отключение

Catch.disable()

всё вернётся как было. хуки снимутся.

Catch.enable()

вернёт обратно.

flush перед выходом

если хочешь гарантированно сбросить лог перед выходом

Catch.flush()

закроет все handler-ы и очистит список. если после flush кто-то добавит handler — он не закроется автоматически.

что внутри

архитектура

основные блоки

контекст через contextvars — trace_id user_id request_id last_error

база ошибок из error_db.json — 1625 записей

логгер catch_errors пишет в errors.log

экспорты — список коллбэков которые вызываются на каждую ошибку

кэш пойманных — set id исключений с LRU на 2000 элементов. хранит только id а не сам exception чтобы traceback не держал фреймы и locals в памяти

rate limiter — класс RateLimiter с окном в 1 секунду

safe repr — пул из 3 daemon потоков с queue на 3 задачи. если repr виснет — воркер не умирает, задача уходит по таймауту с фолбэком на тип

хуки — sys.excepthook threading.excepthook asyncio task_factory и exception_handler

патчи пулов — ProcessPoolExecutor.__init__ и submit у обоих пулов

декораторы — catch_errors async_catch safe_run run_safe

thread safety

почти всё залочено. _enabled_lock для флага включено ли. _output_lock для вывода. _stats_lock для счётчиков. _caught_lock для кэша. _repr_pool_lock для воркеров. contextvars для контекста — автоматически thread-safe и asyncio-safe.

исключения — _excepthook_local через threading.local чтобы не было рекурсии если внутри excepthook снова вылетит ошибка.

известные косяки

safe_repr с пулом потоков — если repr зависнет навсегда воркер останется в памяти. для 99 процентов случаев ок. для продакшена с мусорными объектами лучше выносить в отдельный процесс но это overkill.

enable_asyncio на запущенном loop — существующие таски не подхватятся. только новые. вызывай до asyncio.run.

flush закрывает handler-ы но если кто-то добавит новый после flush он не закроется.

патч ProcessPoolExecutor через inspect.signature может упасть на C-функциях — есть фолбэк на хардкод параметров.

как контрибьютить

форкай пушай PR. если добавляешь ошибку в error_db.json — формать как остальное. если добавляешь фичу — пиши тесты. если ломаешь API — пиши в changelog.

код живой — не бойся оставлять комментарии типа хз почему это работает. не бойся опечаток. не бойся мёртвого кода. всё это признаки того что код писали люди а не генерили машиной.

лицензия

делай что хочёшь. если сломается — сам виноват. если заработает — рад за тебя.

контакты

если нашёл баг — открывай issue с примером воспроизведения. если не можешь воспроизвести — хотя бы логи приложи. если просто хочешь поблагодарить — поставь звезду.

версии

v8.0 — первая рабочая версия. словарь в коде.

v8.1 — словарь вынесен в error_db.json

v9.0 — контекст через contextvars, экспорт в sentry, rate limiter

v9.1 — safe_repr через threading.Timer, weakref для caught

v9.2 — safe_repr через пул потоков, RateLimiter класс, suppress_noise

v9.3 — put_nowait для очереди, inspect.signature для пулов, _log_exception_no_tb

v9.4 — flush только своих handlerов, перезапуск мёртвых воркеров, _handle_exception

v9.5 — фикс deadlock в enable/disable, рекурсия в excepthook через threading.local, last_error_var для asyncio, Windows пути

финал

это не идеальная библиотека. это рабочая штука которая закрывает 95 процентов болей при отладке. если тебе нужно больше — пиши свой форк. код открытый, бери и делай что хочёшь.

удачи с отладкой.
