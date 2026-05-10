# 💡 Overview

**Name:** kwork-scraper
**Description:** Open-source scraper for kwork.ru. Collects services, sellers, prices and reviews into SQLite/PostgreSQL for further analysis.
**Requirements:**
- [httpx](https://pypi.org/project/httpx)
- [dataset](https://pypi.org/project/dataset)
- [fake-useragent](https://pypi.org/project/fake-useragent/)
- [psycopg2-binary](https://pypi.org/project/psycopg2)
# 💻️ Command-line interface design

```bash
# Basic usage, SQLite by default
python3 kwork-scraper.py -c design

# Multiple categories
python3 kwork-scraper.py -c design -c logo/logotipy

# With platform filters
python3 kwork-scraper.py -c design -f sminreview=1 -f sonline=1

# With custom database URL
python3 kwork-scraper.py -c design -d postgresql://user:pass@host/db
```

| Option       | Short | Description                                        | Default              |
| ------------ | ----- | -------------------------------------------------- | -------------------- |
| `--category` | `-c`  | Category slug (repeatable)                         | —                    |
| `--filter`   | `-f`  | Platform filter in `key=value` format (repeatable) | —                    |
| `--database` | `-d`  | Database URL (SQLite or PostgreSQL)                | `sqlite:///kwork.db` |
### 📋️ Expected implementation

Python standard `logging` and `argparse` libraries should be used. All exceptions should be handled and logged accordingly.  Current progress on how much `categories`, `kworks` and `reviews` are already scraped and how much left to scrape should also be logged. Progress tracking can be done internally for `categories`, through `total` field for `kworks` and through `goodReviews` and `badReviews` for `reviews`. All requests should be made with random delay from 1 to 3 seconds. `httpx.Client` aka `session` should be used everywhere rather than raw `httpx.get` or `httpx.post` to maintain cookies. New session per category. Kworks and reviews are requested under same category `session`.

# 🗄️ Database and models

Don't really want to bother with ORM libraries just for parsing. From now on and in future projects, we'll use `dataset` library for such tasks, docs can be found here: https://dataset.readthedocs.io/en/latest/
**Usage example:**
```python
import dataset

db = dataset.connect('sqlite:///:memory:')

table = db['sometable']
table.insert(dict(name='John Doe', age=37))
table.insert(dict(name='Jane Doe', age=34, gender='female'))

john = table.find_one(name='John Doe')
```
## 📚️ Categories model

Categories on Kwork are structured in multiple levels, like this `Дизайн > Логотип и брендинг > Визитки` or like this in slugs `design > logo > logo/vizitki`. `design` is one of several L1 slugs, it doesn't serve any real purpose, since no services are showed on its page, so it just an umbrella. Yet we will also keep it in database to maintain compatibility with website.

Categories are stored in `categories` table using this model:
```python
{
	"id": int, # Autoincrement, because ids can't be easily obtained from website
	"parent_id": int,
	"name": "Визитки",
	"slug": "logo/vizitki"
}
```
## 💼 Kworks model
> Kwork is local name for services listed by sellers

Kworks are stored in `kworks` table using this model:
```python
{
	"id": int, # Collected from kwork itself
	"category_id": int, # Mapped according to our database
	"user_id": int,
	"url": str,
	"price": int,
	"bookmarks": int,
	"queue": int,
	"days": int,
	"average_work_time": int,
	"title": str,
	"description": str,
	"requirements": str,
	"result": str
}
```
**Relations:**
- [[#📦 Packages model]]
- [[#✨ Extras model]]
- [[#💬 Reviews model]]
## 📦 Packages model
>Depends on [[#💼 Kworks model]] 

This model is depends on `kwork` and it stores its offers packages (if there are any), e.g.: `standard` offer includes 2 variants of logo for 5$ and there is a `medium` offer includes 3 variants of logo for 6$ and there is a `premium` offer includes 4 variants and favicon for 8$.

Packages are stored in `packages` table using this model:
```python
{
	"id": int, # Collected from package itself
	"kwork_id": int,
	"type": ["standard","medium","premium"],
	"price": int,
	"days": int,
	"title": str
}
```
## ✨ Extras model
>Depends on [[#💼 Kworks model]] 

This model is also depends on `kwork` and it stores its extras (if there are any), e.g.: you order a logo for 5$ and can buy extra called `profile picture for social media` for 2$

Extras are stored in `extras` table using this model:
```python
{
	"id": int, # Collected from extra itself
	"kwork_id": int,
	"price": int,
	"days": int,
	"title": str,
	"description": str,
	"is_popular": bool
}
```
## 💬 Reviews model
>Depends on [[#💼 Kworks model]] 

Reviews are stored in `reviews` table using this model:
```python
{
	"id": int, # Collected from review itself
	"kwork_id": int,
	"user_id": int,
	"type": ['positive','negative'],
	"time_added": int,
	"comment": str,
}
```
# 👤 Users model

Users are stored in `users` table using this model:
```python
{
	"id": int, # Collected from user itself
	"username": str
}
```
# 🛠️ Scraping

## 💡 Flow overview

```mermaid
flowchart TD
    A([Start]) --> B
    B["Load categories from headerMenu"] --> C
    C["Validate queue, L1 to L2, deduplication"] --> D
    D["POST catalog_kworks_filters/slug, page N"] --> E
    E["GET /url scrape kwork page"] --> F
    F["Parse kwork, user, packages and extras from stateData"] --> G
    G["POST get_reviews positive and negative"] --> I{More pages?}
    I -- yes --> D
    I -- no --> J{More categories?}
    J -- yes --> D
    J -- no --> K([Done])
```
## 🔍️ Everything is stored in `window.stateData`

Scraping libraries like `BeautifulSoup4` or browser automation like `Playwright` are not required, as all the necessary information can be extracted from `window.stateData` right from the html, e.g.: 
```python
import re
import httpx
import json

STATE_DATA_RE = re.compile(r"window\.stateData\s*=\s*({.*?});window\.", re.DOTALL)

html = httpx.get("https://kwork.ru/user/thearialume").text
state_data = json.loads(STATE_DATA_RE.search(html).group(1))
```
Just keep this in mind whenever `window.stateData` is mentioned.
## 📚️ Categories scraping
> Related to [[#📚️ Categories model]]

Entrypoint is `windows.stateData.headerMenu`, where `headerMenu` is an `array` with the following structure:
```javascript
[
    {
        "id": 69, // Website's id should be ignored, use database autoincrement instead
        "url": "https://kwork.ru/categories/design",
        "name": "Дизайн", // L1 category
        "columns": [
            {
                "isFirstGroup": true,
                "items": [
                    {
                        "name": "Логотип и брендинг", // L2 category
                        "isFire": false,
                        "isTagNew": false,
                        "isTagBeta": false,
                        "children": [
                            [
                                {
                                    "name": "Логотипы", // L3 category
                                    "url": "https://kwork.ru/categories/logo/logotipy",
                                    "isFire": true,
                                    "isTagNew": false,
                                    "isTagBeta": false
                                },
                                {
                                    "name": "Фирменный стиль", // L3 category
                                    "url": "https://kwork.ru/categories/logo/firmenniy-stil", // L3 category
                                    "isFire": false,
                                    "isTagNew": false,
                                    "isTagBeta": false
                                },
                                {
                                    "name": "Визитки", // L3 category
                                    "url": "https://kwork.ru/categories/logo/vizitki",
                                    "isFire": false,
                                    "isTagNew": false,
                                    "isTagBeta": false
                                },
                                {
                                    "name": "Брендирование и сувенирка", // L3 category
                                    "url": "https://kwork.ru/categories/logo/brendirovanie-i-suvenirka",
                                    "isFire": false,
                                    "isTagNew": false,
                                    "isTagBeta": false
                                }
                            ]
                        ]
                    },
// Structure is repeated after that
```
`Логотипы` category is a child of `Логотип и брендинг` category while it is a child of `Дизайн` category. There are only 3 levels of categories, there is no need to dive any deeper. `columns` are only needed for website UI, so they make no practical sense for us at all.

It's interesting that the L2 categories don't have an obtainable slug from website, but it can easily be obtained through any of their children, e.g.:  `Логотипы` slug is `logo/logotipy` so its parent `Логотип и брендинг` will have `logo` slug
### 📋️ Expected command-line behaviour
>Related to [[#💻️ Command-line interface design]]

When user adds `categories` to scrape, you should query database to check its level. All L1 categories should be removed and their L2 children should be added to queue instead, because there is nothing to scrape at L1's slugs as it was stated before.

For L2 `categories`, this is not required, a search within their catalog automatically includes their children results. 

Before starting the scraping, ensure that the elements are not duplicated. It also means, if L3 `categories` are added by user and their L2 parent is also included, L3 `categories` should be removed and user should be warned about this.
## 🗃️ Catalog scraping

Queries are being made to:
```
POST https://kwork.ru/catalog_kworks_filters/<slug>
```

For example, here is a copy of the request from the second page filtered to include a minimum of one review in cURL format.
```bash
curl 'https://kwork.ru/catalog_kworks_filters/logo/logotipy' \
  --compressed \
  -X POST \
  -H 'User-Agent: Mozilla/5.0 (X11; Linux x86_64; rv:143.0) Gecko/20100101 Firefox/143.0' \
  -H 'Accept: application/json, text/plain, */*' \
  -H 'Accept-Language: en-US,en;q=0.5' \
  -H 'Accept-Encoding: gzip, deflate, br, zstd' \
  -H 'X-Requested-With: XMLHttpRequest' \
  -H 'Content-Type: multipart/form-data; boundary=----geckoformboundary7eb99b534fe3150abc344fcb9329873d' \
  -H 'Origin: https://kwork.ru' \
  -H 'Connection: keep-alive' \
  -H 'Referer: https://kwork.ru/categories/logo/logotipy?sminreview=1' \
  -H 'Sec-Fetch-Dest: empty' \
  -H 'Sec-Fetch-Mode: cors' \
  -H 'Sec-Fetch-Site: same-origin' \
  -H 'Priority: u=0' \
  --data-binary \
  $'------geckoformboundary7eb99b534fe3150abc344fcb9329873d\r\nContent-Disposition: form-data; name="sminreview"\r\n\r\n1\r\n------geckoformboundary7eb99b534fe3150abc344fcb9329873d\r\nContent-Disposition: form-data; name="page"\r\n\r\n2\r\n------geckoformboundary7eb99b534fe3150abc344fcb9329873d\r\nContent-Disposition: form-data; name="excludeIds"\r\n\r\n104445,34822518,38674574,18658149,9733560,9332464,9564042,34821619,5505798,18803992,1222611,67108,2510482,20848768,83042,19160944,247761,2745,22812218,20869474,32539303,15280132,8138,7418394\r\n------geckoformboundary7eb99b534fe3150abc344fcb9329873d\r\nContent-Disposition: form-data; name="onePage"\r\n\r\n1\r\n------geckoformboundary7eb99b534fe3150abc344fcb9329873d\r\nContent-Disposition: form-data; name="paymentTypes[]"\r\n\r\n\r\n------geckoformboundary7eb99b534fe3150abc344fcb9329873d--\r\n'
```
Both `page` and `excludeIds` arguments are required for pagination to work. `excludeIds` is populated with all the kworks found beginning from the first to the  current page.

Response structure is the following:
```javascript
{
    "success": true,
    "data": {
        "stateData": {
            "viewData": {
	            "filters": {} // Truncated because it's not needed for us 
                "kworks": {
                    "activeCategoryId": 25,
                    "sdisplay": "table",
                    "s": "groups",
                    "items_per_page": 24,
                    "currentpage": 2,
                    "statActKworksCount": 755155,
                    "filterQuery": "sminreview=1&page=2",
                    "total": 836,
                    "total_found": 836,
                    "posts": {
                        "total": null,
                        "data": [
                            {
                                "id": 8969,
                                "url": "/logo/8969/sozdayu-professionalnie-logotipy",
                                "photo": "31/8969-6956bfd81e1cd.jpg?ver=1455010331",
                                "gtitle": "Создаю профессиональные логотипы",
                                "userId": 15751,
                                "userName": "YAnna",
                                "userIsOnline": false,
                                "rating": 640,
                                "userRating": 98,
                                "convertedUserRating": "4.9",
                                "userBackground": "#ee7aae",
                                "userRatingCount": "945",
                                "price": 10000,
                                "lang": "ru",
                                "isFrom": true,
                                "bonusText": "",
                                "bonusModerateStatus": 0,
                                "isFavorite": false,
                                "isHidden": false,
                                "sellerIsNotAvailable": false,
                                "hintWorker": "",
                                "hintPayer": "",
                                "topBadge": false,
                                "baseVolumePrice": null,
                                "baseVolumeShortName": null,
                                "baseVolume": null,
                                "packageVolume": 0,
                                "sellerLevel": 2,
                                "isBlackFriday": null,
                                "userMarkClass": "",
                                "userMarkText": "",
                                "markType": "",
                                "queueCount": 0,
                                "days": 3
                            },
                            // Structure is repeated after that
                        ]
                    },
                    "seoAddText": null,
                    "seoFaq": null
                }
            }
        }
    }
}
```
Everything we need to collect from `catalog` are urls and ids (for `excludeIds`), because all of the information we need can be found on kwork page.
## 💼 Kwork scraping
> Related to [[#💼 Kworks model]], [[#📦 Packages model]] and [[#👤 Users model]]

Queries are being made to:
```
GET https://kwork.ru/<url obtained from catalog>
```

After downloading page's content, entrypoint to data is `windows.stateData.kwork`, where `kwork` is a `dictionary` with the following structure:
```json
{
  "activeStatus": 1,
  "blockType": "",
  "bookmarkCount": 404,
  "category": "38", // Never use it, map category id according to our database, using slug
  "categoryTitle": "Доработка и настройка сайта", 
  "categoryUrl": "categories/website-repair", // Remove categories/ and extract slug from here for category_id mapping 
  "avgWorkTime": "171374",
  "gdesc": "<p><strong>Повышение удобства и эффективности интернет-магазина за счёт точной доработки интерфейса и контента под бизнес-задачи.</strong></p><p><strong>Что входит в услугу</strong></p><ol><li>Изменение расположения и структуры блоков</li><li>Скрытие или удаление отдельных элементов</li><li>Корректировка текстового содержимого и заголовков</li><li>Настройка размеров элементов интерфейса</li><li>Изменение параметров шрифтов</li></ol>",
  "ginst": "<ol><li>URL-сайта,</li><li>логин; пароль от админ-панели,</li><li>FTP (или URL, логин; пароль от панели управления хостингом),</li><li>наличие бэкапа на хостинге на дату оформленного заказа </li></ol>",
  "gtitle": "Правки и доработка сайта с гарантией. Opencart, Опенкарт, Ocstore",
  "days": "3",
  "gwork": "1 правка", // Result field for kworks
  "hasOffer": null,
  "id": 170786,
  "isResizing": "0",
  "queueCount": "0",
  "isPackage": false,
  "isTopBadge": true,
  "isUserBlocked": false,
  "lang": "ru",
  "name": "Доработка и настройка сайта",
  "packages": [],
  "price": 1000,
  "displayedPrice": 1000,
  "displayedDiscountPrice": null,
  "minVolumePrice": 1000, // Take this as a price
  "seo": "website-repair",
  "url": "/website-repair/170786/pravki-i-dorabotka-sayta-s-garantiey-opencart-openkart-ocstore",
  "userId": 246549, // id for users
  "username": "codee", // username for users
  "volume_type_id": null,
  "volume": "0"
}
```

Or it can be slightly different, if it is package kwork:
```json
{
  "activeStatus": 1,
  "blockType": "",
  "bookmarkCount": 70,
  "category": "25", // Never use it, map category id according to our database, using slug
  "categoryTitle": "Логотип и брендинг",
  "categoryUrl": "categories/logo", // Remove categories/ and extract slug from here for category_id mapping 
  "avgWorkTime": "125336",
  "coverBase64": null,
  "gdesc": "<p><strong>Ваш логотип</strong> - это первое, по чему клиент оценивает ваш бизнес.</p><p>И если он выглядит дёшево или “как у всех” - вы теряете доверие ещё до того, как с вами начали работать.  </p><p><strong>Я разработаю логотип, который:</strong></p><p>• <em>Выделит вас среди конкурентов</em></p><p>• <em>Будет выглядеть профессионально</em></p><p>• <em>Создаст правильное первое впечатление</em></p><p><strong>Почему выбирают меня</strong>: </p><p>Я не просто “рисую логотип”.  </p><p>Я создаю визуальный образ, который:</p><p>• <em>Отражает суть вашего бизнеса</em></p><p>• <em>Усиливает восприятие бренда</em></p><p>• <em>Делает вас визуально дороже</em></p><p><strong>Что вы получите:</strong></p><p>• <em>Уникальный логотип, разработанный с нуля</em></p><p>• <em>Несколько концепций на выбор</em></p><p>• <em>Доработку до финального результата</em></p><p>• <em>Чистый и современный дизайн</em></p><p>• <em>Логотип, который будет работать в реальных задачах</em></p><p><strong>Итог:</strong></p><p>После утверждения вы получите полный комплект:</p><p>• <em>Исходники: AI, EPS, PDF</em></p><p>• <em>Форматы: PNG, JPG, SVG</em></p><p>• <em>Подготовка под печать и онлайн</em></p><p><strong>Важно:</strong></p><p>Если вам нужен “быстрый и самый дешёвый вариант” - скорее всего, я не подойду.</p><p>Если вам нужен логотип, с которым можно уверенно развивать бизнес - мы сработаемся.</p><p>Напишите: «Хочу логотип» - обсудим бриф и я разработаю логотип под Ваш бизнес</p>",
  "ginst": "<p><strong>• Название</strong></p><p><em>(как называется ваша компания / бренд)</em></p><p><strong>• Дескриптор</strong></p><p><em>(короткая подпись под названием)</em></p><p><strong>• Чем вы занимаетесь</strong></p><p><em>(основные услуги или направление бизнеса)</em></p><p><strong>• Какой стиль вам ближе</strong></p><p><em>(строгий, минимализм, премиум, женственный и т.д.)</em></p><p><strong>• Какой символ или образ хотите видеть</strong></p><p><em>(например: у Apple - яблоко, у Red Bull - два быка)</em></p><p><strong>• Примеры, которые нравятся</strong></p><p><em>(2–3 логотипа, которые вам ближе всего)</em></p><p><strong>• Пожелания по цветам</strong></p><p><em>(любимые цвета или те, которые не использовать)</em></p>",
  "gtitle": "Дизайн логотипа. Логотип для бизнеса под ключ. Уникальный логотип",
  "days": "3",
  "gwork": "", // Result field for kworks, missing in packaged kworks, use "standard" package title/description instead
  "hasOffer": null,
  "id": 34822518,
  "isResizing": "0",
  "queueCount": "0",
  "isNeedModerate": true,
  "isPackage": true,
  "isTopBadge": true,
  "isUserBlocked": false,
  "lang": "ru",
  "name": "Логотип и брендинг",
  "packages": {
    "standard": {
      "id": 6969369,
      "type": "standard", // type field for packages
      "desc": "2 варианта логотипа", // title field for packages
      "price": 4000,
      "duration": 3, // days field for packages
      "minDuration": 3,
      "minVolume": 1,
      "minVolumePrice": 4000, // Take this as a price
      "packageName": "Эконом",
    },
    "medium": {
      "id": 6992380,
      "type": "medium", // type field for packages
      "desc": "3 варианта логотипа", // title field for packages
      "price": 5000,
      "price_ctp": 1000,
      "duration": 3, // days field for packages
      "minDuration": 3,
      "minVolume": 1,
      "minVolumePrice": 5000, // Take this as a price
      "packageName": "Стандарт",
    },
    "premium": {
      "id": 6992383,
      "type": "premium", // type field for packages
      "desc": "4 варианта логотипа", // title field for packages
      "price": 6000,
      "duration": 3, // days field for packages
      "minDuration": 3,
      "minVolume": 1,
      "minVolumePrice": 6000, // Take this as a price
      "packageName": "Бизнес",
    }
  },
  "price": 4000,
  "displayedPrice": 4000,
  "displayedDiscountPrice": null,
  "minVolumePrice": 4000, // Take this as a price
  "commonRejectReason": null,
  "rejectFieldsString": null,
  "seo": "logo",
  "url": "/logo/34822518/dizayn-logotipa-logotip-dlya-biznesa-pod-klyuch-unikalniy-logotip",
  "userId": 9832208, // id for users
  "username": "DESIGN-LOGO", // username for users
  "volume_type_id": null,
  "volume": "0"
}
```

Extras also can be obtained from this page, entrypoint for them is `window.stateData.extras`, where `extras` is an `array` with the following structure:
```json
[
  {
    "id": 61302314,
    "localizedPrice": "500",
    "isPopular": false,
    "description": "Вы гарантированно получите логотипы в течении 24 часов. Вам не придётся ожидать очереди",
    "title": "Срочное выполнение заказа",
    "price": 500, // Take this as a price
    "duration": 0, // Take this as days field
    "localizedPriceString": "500 <span >₽</span>",
  },
  {
    "id": 61302317,
    "localizedPrice": "200",
    "isPopular": true,
    "description": "Это круглая обложка для соц. сетей, которая показывает лицо Вашей компании",
    "title": "Аватарка с логотипом для соц. сетей",
    "price": 200, // Take this as a price
    "duration": 0, // Take this as days field
    "localizedPriceString": "200 <span>₽</span>",
  },
  {
    "id": 61302320,
    "localizedPrice": "200",
    "isPopular": true,
    "description": "Векторный логотип для сайта (масштабируемый формат без потери качества)",
    "title": "SVG формат - для сайта",
    "price": 200, // Take this as a price
    "duration": 0, // Take this as days field
    "localizedPriceString": "200 <span >₽</span>",
  }
]
```

## 💬 Reviews scraping
>Related to [[#💬 Reviews model]] and [[#👤 Users model]]
>Don't forget to also add reviewer's account to the users table

Queries are being made to:
```
POST https://kwork.ru/kwork/get_reviews
```

With the following request for `positive`:
```json
{"id":34822518,"type":"positive","offset":0,"limit":12}
```

Or a little bit different for `negative`:
```json
{"id":34822518,"type":"negative","offset":0,"limit":12}
```

Response structure:
```json
{
    "success": true,
    "data": {
        "reviews": [
            {
                "RID": "0000", // Redacted for privacy
                "comment": "...", // Redacted for privacy
                "good": "1",
                "bad": "0",
                "time_added": 1776702442,
                "PID": 0,
                "order_id": 0, // Take this as id for reviews, because there can be only one review per order and I'm not sure what are RID or PID for
                "auto_mode": null,
                "USERID": "0000", // Redacted for privacy
                "orderLang": "ru",
                "username": "...", // Redacted for privacy
                "profilepicture": "noprofilepicture.gif",
                "avatarBackground": "#e17076",
                "time_ago": "19 дней",
                "hasPaidStages": false,
                "raterDisplayName": "...." // Redacted for privacy
            }
            // Structure repeats after that
        ],
        "goodReviews": 135,
        "badReviews": 0,
        "ratingAverage": {
            "id": 16922,
            "kwork_id": 34822518,
            "speed": 5,
            "quality": 5,
            "communication": 5,
            "created_at": "2024-08-16 20:06:50",
            "updated_at": null
        }
    }
}
```

Copy of request in cURL format if needed:
```bash
curl 'https://kwork.ru/kwork/get_reviews' \
  --compressed \
  -X POST \
  -H 'User-Agent: Mozilla/5.0 (X11; Linux x86_64; rv:143.0) Gecko/20100101 Firefox/143.0' \
  -H 'Accept: application/json, text/plain, */*' \
  -H 'Accept-Language: en-US,en;q=0.5' \
  -H 'Accept-Encoding: gzip, deflate, br, zstd' \
  -H 'Content-Type: application/json' \
  -H 'X-Requested-With: XMLHttpRequest' \
  -H 'Origin: https://kwork.ru' \
  -H 'Connection: keep-alive' \
  -H 'Referer: https://kwork.ru/logo/34822518/dizayn-logotipa-logotip-dlya-biznesa-pod-klyuch-unikalniy-logotip' \
  -H 'Sec-Fetch-Dest: empty' \
  -H 'Sec-Fetch-Mode: cors' \
  -H 'Sec-Fetch-Site: same-origin' \
  -H 'Priority: u=0' \
  --data-raw '{"id":34822518,"type":"positive","offset":5,"limit":12}'
```