# 💡 kwork-scraper

Open-source скрапер для [kwork.ru](https://kwork.ru). Собирает услуги, пользователей, цены и отзывы в SQLite/PostgreSQL для дальнейшего анализа.

# 🚀 Быстрый старт

```bash
# Клонировать репозиторий
git clone https://github.com/your-username/kwork-scraper.git
cd kwork-scraper

# Установить зависимости
pip install -r requirements.txt

# Запустить (SQLite по умолчанию)
python3 kwork-scraper.py -c design
```

# 💻️ Интерфейс командной строки

```bash
# Базовое использование, SQLite по умолчанию
python3 kwork-scraper.py -c design

# Несколько категорий
python3 kwork-scraper.py -c design -c logo/logotipy

# С фильтрами платформы
python3 kwork-scraper.py -c design -f sminreview=1 -f sonline=1

# С указанием базы данных
python3 kwork-scraper.py -c design -d postgresql://user:pass@host/db

# С кастомными задержками между запросами
python3 kwork-scraper.py -c design -D 0.5 2.5

# Пропустить кворки, которые уже в базе данных
python3 kwork-scraper.py -c design -s
```

| Опция        | Короткая | Описание                                           | По умолчанию         |
| ------------ | -------- | -------------------------------------------------- | -------------------- |
| `--category` | `-c`     | Слаг категории (можно указать несколько)           |                    |
| `--filter`   | `-f`     | Фильтр платформы в формате `key=value` (повторяемый) |                  |
| `--database` | `-d`     | URL базы данных (SQLite или PostgreSQL)            | `sqlite:///kwork.db` |
| `--delay`    | `-D`     | Диапазон задержки запросов в секундах: MIN MAX     | `1.0 3.0`            |

# 🗄️ База данных

Поддерживаются SQLite (по умолчанию) и PostgreSQL. Используется библиотека [`dataset`](https://pypi.org/project/dataset).

## 📚️ categories

Категории хранятся в иерархии: `design` (L1) → `logo/vizitki` (L2). L1-категории являются зонтичными услуги на них не размещаются, но в базе сохраняются для совместимости с сайтом.

| Поле        | Тип | Описание                         |
| ----------- | --- | -------------------------------- |
| `id`        | int | Автоинкремент                    |
| `parent_id` | int | Ссылка на родительскую категорию |
| `name`      | str | Название, например `Визитки`     |
| `slug`      | str | Слаг, например `logo/vizitki`    |

## 💼 kworks

Основная таблица. Kwork это услуга, размещённая продавцом.

| Поле                | Тип | Описание                         |
| ------------------- | --- | -------------------------------- |
| `id`                | int | ID с сайта                       |
| `category_id`       | int | → `categories.id`                |
| `user_id`           | int | → `users.id`                     |
| `url`               | str | Относительный URL услуги         |
| `price`             | int | Цена                             |
| `bookmarks`         | int | Количество добавлений в закладки |
| `queue`             | int | Очередь заказов                  |
| `days`              | int | Срок выполнения                  |
| `average_work_time` | int | Среднее время выполнения         |
| `title`             | str | Заголовок                        |
| `description`       | str | Описание                         |
| `requirements`      | str | Что нужно от покупателя          |
| `result`            | str | Что получит покупатель           |

## 📦 packages

Пакеты услуги `standard`, `medium`, `premium`. Присутствуют не у всех kwork'ов.

| Поле       | Тип                                    | Описание        |
| ---------- | -------------------------------------- | --------------- |
| `id`       | int                                    | ID с сайта      |
| `kwork_id` | int                                    | → `kworks.id`   |
| `type`     | `standard` \| `medium` \| `premium`   | Тип пакета      |
| `price`    | int                                    | Цена пакета     |
| `days`     | int                                    | Срок выполнения |
| `title`    | str                                    | Название        |

## ✨ extras

Дополнительные опции к услуге, например «Срочное выполнение» или «Аватарка для соцсетей».

| Поле          | Тип  | Описание         |
| ------------- | ---- | ---------------- |
| `id`          | int  | ID с сайта       |
| `kwork_id`    | int  | → `kworks.id`    |
| `price`       | int  | Цена             |
| `days`        | int  | Доп. дней        |
| `title`       | str  | Название         |
| `description` | str  | Описание         |
| `is_popular`  | bool | Популярная опция |

## 💬 reviews

Отзывы покупателей положительные и отрицательные.

| Поле         | Тип                       | Описание           |
| ------------ | ------------------------- | ------------------ |
| `id`         | int                       | `order_id` с сайта |
| `kwork_id`   | int                       | → `kworks.id`      |
| `user_id`    | int                       | → `users.id`       |
| `type`       | `positive` \| `negative` | Тип отзыва         |
| `time_added` | int                       | Unix timestamp     |
| `comment`    | str                       | Текст отзыва       |

## 👤 users

Продавцы и авторы отзывов.

| Поле       | Тип | Описание          |
| ---------- | --- | ----------------- |
| `id`       | int | ID с сайта        |
| `username` | str | Имя пользователя  |

# 📦 Зависимости

- [httpx](https://pypi.org/project/httpx): HTTP-клиент
- [dataset](https://pypi.org/project/dataset): работа с базой данных
- [fake-useragent](https://pypi.org/project/fake-useragent/): случайные user-agent заголовки
- [psycopg2-binary](https://pypi.org/project/psycopg2): поддержка PostgreSQL

# 📄 Лицензия

[MIT](LICENSE) © 2026 [Tolko](mailto:contact@tolko.cc) and [Aria Lume](mailto:thearialume@gmail.com)