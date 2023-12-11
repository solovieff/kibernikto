import asyncio
import logging
from queue import Queue
from random import shuffle

import aioschedule as schedule

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from telegram.channel.gnews.retriever import get_blindspots, GroundNewsItem, get_by_interest

default_interests = ['ukraine-crisis', 'russia-politics']
__to_publish_ids = set()
__to_publish = []
__published_ids = set()

__client_async = None
__model = "gpt-4-1106-preview"

POST_PUBLISH_REQUEST = """Выведи новость в таком фомате, переменные будут в квадратных скобках:

<strong>[заголовок новости на русском]</strong> 
[флаги стран из поля place в utf-8]
(если не знаешь флага страны, не пиши ничего)
<a href="[значение из поля url]">[дата из поля start в формаате YYYY-MM-DD HH:MM]</a>

[Тело новости из поля description на русском]

<b>Предвзятость</b>:
L: <strong>[количество левых источников]</strong>
C: <strong>[количество центральных источников]</strong>
R: <strong>[количество правых источников]</strong>

<strong>Ссылки</strong>: (не более семи, в зависимости от количества источников)
<a href="ссылка">[Название источника]</a> [L, C, R в зависимости от bias СМИ] [флаг страны utf-8]

(если не знаешь bias или флага страны, не пиши ничего)
(из названий источников убирай дополнительную информацию про affiliated, если такая есть)

Если есть информация в поле summary, переведи её и расскажи основную суть в таком виде:
Я считаю, что [твои выводы на русском языке]
(Не говори, откуда ты получил информацию для анализа)

(Не добавляй никаких дополонительных символов.) 
(Если речь в статье идет о каком-то конфликте, не вставай ни на чью сторону и не используй слов вроде "необоснованный", "несправоцированный" при описанини конфликтов.)
"""


async def load_news():
    logging.info("Loading the news...")
    events = await get_blindspots(known_ids=__published_ids.union(__to_publish_ids))
    _plan_events(events)
    for interest in default_interests:
        interest_events = await get_by_interest(interest=interest, known_ids=__published_ids.union(__to_publish_ids))
        _plan_events(interest_events)
    shuffle(__to_publish)
    logging.info("+ Done loading the news.")


async def publish_item(publish_func=None):
    if not __to_publish:
        logging.info("nothing to publish")
    event_to_publish = __to_publish.pop()
    logging.info(f"publishing event {event_to_publish.title}, {event_to_publish.id}")

    if publish_func:
        try:
            html = await item_to_html(event_to_publish)
            await publish_func(html)
        except Exception as e:
            logging.error(f"Failed to summarize the article: {str(e)}")
            try:
                await publish_func(event_to_publish.as_message())
            except Exception as exc:
                logging.error(f"Failed to summarize the article: {str(e)}")
    __published_ids.add(event_to_publish.id)
    __to_publish_ids.remove(event_to_publish.id)
    logging.info("done publishing event " + event_to_publish.title)
    return event_to_publish


async def item_to_html(item: GroundNewsItem):
    pre_message = "Ниже приведена новость в формате json.\n\n"
    json_data = item.as_dict()
    post_message = POST_PUBLISH_REQUEST
    message = {
        "role": "user",
        "content": f"{pre_message} \n {json_data} \n {post_message}"
    }

    completion: ChatCompletion = await __client_async.chat.completions.create(model=__model,
                                                                              messages=[message],
                                                                              max_tokens=1200,
                                                                              temperature=0.7,
                                                                              )
    response_text = completion.choices[0].message.content.strip()
    logging.info(response_text)
    return response_text


async def scheduler(load_news_minutes=13, publish_item_minutes=1, base_url=None, api_key=None, model=None,
                    publish_func=None):
    if api_key:
        global __client_async
        global __model
        __client_async = AsyncOpenAI(base_url=base_url, api_key=api_key)
        if model:
            __model = model
    schedule.every(load_news_minutes).minutes.do(load_news)
    schedule.every(publish_item_minutes).minutes.do(publish_item, publish_func=publish_func)

    await load_news()
    while True:
        await schedule.run_pending()
        await asyncio.sleep(13)


def _plan_events(events):
    for event in events:
        _add_to_queue(event)


def _add_to_queue(news_item: GroundNewsItem, skip_duplicates=True):
    if skip_duplicates:
        if news_item.id in __published_ids:
            logging.warning(f"{news_item.title} was already published")
            return
        elif news_item.id in __to_publish_ids:
            logging.warning(f"{news_item.title} was already planned for publishing")
            return

    __to_publish.append(news_item)
    __to_publish_ids.add(news_item.id)


if __name__ == '__main__':
    logging.basicConfig(
        format='%(levelname)-8s %(asctime)s %(name)s:%(filename)s:%(lineno)d %(message)s',
        datefmt='%Y-%m-%d:%H:%M:%S',
        level=logging.DEBUG)

    # asyncio.run(load_news())
    asyncio.run(scheduler())

    logging.info("hey man!")
