# camsort V3 — сортировка видеозаписей по датам и временным интервалам.
# Автор: Симоненко К.В. 2026
# Стандартная библиотека Python, без внешних зависимостей.

import os
import re
import shutil
import argparse
import configparser
import sys
from datetime import datetime, timedelta


def expand_dates(raw, name):
    # "2026-10-12..2026-10-16, 2026-11-09" -> список дат ГГГГ-ММ-ДД
    result = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ".." in chunk:
            a, b = [x.strip() for x in chunk.split("..", 1)]
            try:
                da = datetime.strptime(a, "%Y-%m-%d").date()
                db = datetime.strptime(b, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError(f"Некорректный диапазон в {name}: {chunk} (ожидается ГГГГ-ММ-ДД..ГГГГ-ММ-ДД)")
            if da > db:
                raise ValueError(f"В {name} начало диапазона позже конца: {chunk}")
            cur = da
            while cur <= db:
                result.append(cur.strftime("%Y-%m-%d"))
                cur += timedelta(days=1)
        else:
            try:
                datetime.strptime(chunk, "%Y-%m-%d")
            except ValueError:
                raise ValueError(f"Некорректная дата в {name}: {chunk} (ожидается ГГГГ-ММ-ДД)")
            result.append(chunk)
    return result


def load_config(path):
    # Читает INI-конфиг (UTF-8), без интерполяции %-символов
    parser = configparser.ConfigParser(interpolation=None)
    if not parser.read(path, encoding="utf-8"):
        raise SystemExit(f"Не удалось прочитать конфиг: {path}")

    section = "settings"
    if not parser.has_section(section):
        raise SystemExit(f"В конфиге нет секции [{section}]")

    # Собирает строковые поля и флаг overwrite из секции [settings]
    cfg = {
        "src_dir": parser.get(section, "src_dir", fallback="").strip(),
        "dst_dir": parser.get(section, "dst_dir", fallback="").strip(),
        "filename_regex": parser.get(section, "filename_regex", fallback="").strip(),
        "date_format": parser.get(section, "date_format", fallback="").strip(),
        "time_format": parser.get(section, "time_format", fallback="").strip(),
        "overwrite": parser.getboolean(section, "overwrite", fallback=False),
    }

    # Проверяет, что обязательные строковые поля не пустые
    for key in ("src_dir", "dst_dir", "filename_regex", "date_format", "time_format"):
        if not cfg[key]:
            raise ValueError(f"В конфиге не задано поле: {key}")

    # Разбирает интервалы: "09:00-10:00, 11:00-12:30" -> список пар
    raw_intervals = parser.get(section, "intervals", fallback="").strip()
    intervals = []
    if raw_intervals:
        for chunk in raw_intervals.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "-" not in chunk:
                raise ValueError(f"Интервал должен быть в формате ЧЧ:ММ-ЧЧ:ММ: {chunk}")
            a, b = [x.strip() for x in chunk.split("-", 1)]
            intervals.append([a, b])
    cfg["intervals"] = intervals

    # Разбирает белый и чёрный списки, поддерживает диапазоны ГГГГ-ММ-ДД..ГГГГ-ММ-ДД
    cfg["whitelist"] = expand_dates(parser.get(section, "whitelist", fallback=""), "whitelist")
    cfg["blacklist"] = expand_dates(parser.get(section, "blacklist", fallback=""), "blacklist")

    # Режим фильтра по типу дня: all | weekdays | weekends
    day_type = parser.get(section, "day_type", fallback="all").strip().lower()
    if day_type not in ("all", "weekdays", "weekends"):
        raise ValueError(f"day_type должен быть all/weekdays/weekends, получено: {day_type}")
    cfg["day_type"] = day_type

    # Проверяет интервалы: пара ЧЧ:ММ, начало не позже конца
    for pair in cfg["intervals"]:
        if len(pair) != 2:
            raise ValueError(f"Интервал должен быть парой: {pair}")
        a = datetime.strptime(pair[0], "%H:%M").time()
        b = datetime.strptime(pair[1], "%H:%M").time()
        if not (a <= b):
            raise ValueError(f"Некорректный интервал (начало должно быть не позже конца): {pair}")

    return cfg


def parse_intervals(cfg):
    # Превращает строки "ЧЧ:ММ" в объекты time для сравнения
    return [
        (datetime.strptime(a, "%H:%M").time(),
         datetime.strptime(b, "%H:%M").time())
        for a, b in cfg["intervals"]
    ]


def in_intervals(t, intervals):
    # Пустой список интервалов — без фильтра по времени (любое время подходит)
    if not intervals:
        return True
    # Границы включительно: start <= t <= end.
    # Для ["09:00","10:00"] запись 10:00:00 попадёт, 10:00:01 — уже нет.
    for a, b in intervals:
        if a <= t <= b:
            return True
    return False


def day_allowed(day_str, cfg):
    # Фильтр по типу дня: all — без фильтра, weekdays — пн–пт, weekends — сб–вс
    day_type = cfg["day_type"]
    if day_type != "all":
        wd = datetime.strptime(day_str, "%Y-%m-%d").weekday()  # 0=пн, 6=вс
        is_weekend = wd >= 5
        if day_type == "weekdays" and is_weekend:
            return False
        if day_type == "weekends" and not is_weekend:
            return False
    # Затем белый список: если задан — день должен быть в нём
    if cfg["whitelist"] and day_str not in cfg["whitelist"]:
        return False
    # Затем чёрный: если день в нём — исключаем
    if day_str in cfg["blacklist"]:
        return False
    return True


def run(config_path, progress_cb=None):
    # Выполняет сортировку по указанному конфигу.
    # progress_cb(done, total) вызывается после каждого обработанного файла (для GUI).
    cfg = load_config(config_path)

    src = cfg["src_dir"]
    dst = cfg["dst_dir"]
    if not os.path.isdir(src):
        raise SystemExit(f"Входной каталог не найден: {src}")

    # Компилирует regex, готовит форматы и интервалы
    rx = re.compile(cfg["filename_regex"])
    date_fmt = cfg["date_format"]
    time_fmt = cfg["time_format"]
    intervals = parse_intervals(cfg)
    overwrite = cfg["overwrite"]

    # Создаёт выходной каталог, если его нет
    os.makedirs(dst, exist_ok=True)

    # Счётчики для итоговой статистики
    copied = skipped_format = skipped_day = skipped_interval = skipped_exists = 0

    # Список файлов верхнего уровня (для прогресса)
    names = [n for n in sorted(os.listdir(src)) if os.path.isfile(os.path.join(src, n))]
    total = len(names)
    done = 0

    # Обходит файлы верхнего уровня входного каталога
    for name in names:
        src_path = os.path.join(src, name)
        done += 1
        if progress_cb:
            progress_cb(done, total)

        # Извлекает дату и время начала из имени файла
        m = rx.match(name)
        if not m:
            print(f"[SKIP] имя не подходит под шаблон: {name}")
            skipped_format += 1
            continue

        d = datetime.strptime(m.group("date"), date_fmt).date()
        t = datetime.strptime(m.group("time"), time_fmt).time()
        day_str = d.strftime("%Y-%m-%d")

        # Фильтр по белому и чёрному спискам
        if not day_allowed(day_str, cfg):
            skipped_day += 1
            continue

        # Фильтр по временным интервалам
        if not in_intervals(t, intervals):
            skipped_interval += 1
            continue

        # Копирует в папку дня (создаёт, если её ещё нет)
        day_dir = os.path.join(dst, day_str)
        os.makedirs(day_dir, exist_ok=True)
        dst_path = os.path.join(day_dir, name)

        # Если файл уже есть — пропускает или перезаписывает по настройке overwrite
        if os.path.exists(dst_path) and not overwrite:
            print(f"[SKIP] уже существует: {day_str}/{name}")
            skipped_exists += 1
            continue

        shutil.copy2(src_path, dst_path)
        copied += 1
        print(f"[COPY] {name} -> {day_str}/")

    # Итоговая сводка
    print("---")
    print(f"Скопировано:           {copied}")
    print(f"Пропущено (шаблон):    {skipped_format}")
    print(f"Пропущено (день):      {skipped_day}")
    print(f"Пропущено (интервал):  {skipped_interval}")
    print(f"Пропущено (уже есть):  {skipped_exists}")

    return {
        "copied": copied,
        "skipped_format": skipped_format,
        "skipped_day": skipped_day,
        "skipped_interval": skipped_interval,
        "skipped_exists": skipped_exists,
        "total": total,
    }


def main():
    # Если -c не передан, берёт config.txt рядом со скриптом (или .exe)
    ap = argparse.ArgumentParser(description="Сортировка записей по дате и временным интервалам")
    ap.add_argument("-c", "--config", required=False, help="Путь к INI-конфигу")
    args = ap.parse_args()

    if args.config:
        config_path = args.config
    else:
        base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        config_path = os.path.join(base_dir, "config.txt")

    run(config_path)


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if e.code not in (None, 0):
            print(e.code)
    except Exception as e:
        print(f"ОШИБКА: {e}")
    finally:
        input("Нажмите Enter для выхода...")