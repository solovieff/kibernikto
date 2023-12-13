import asyncio
import json
import logging
import traceback
from json import JSONDecodeError
from random import shuffle
from xml.sax.saxutils import quoteattr

from kibernikto import constants
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from kibernikto.telegram.channel.gnews.retriever import get_blindspots, GroundNewsItem, get_by_interest

default_interests = constants.TG_CHANNEL_INTERESTS
__to_publish_ids = set()
__to_publish = []
__published_ids = set()

__client_async = None
__model = "gpt-4-1106-preview"

__system_message = {
    'role': 'system',
    'content': """
    Now you speak as a powerful member of a secret Masonic lodge named Kibernikto. 
    Kibernikto jokes in a sinister manner and sometimes says dirty words.   
    Kibernikto speech is very cynic, arrogant and sarcastic. He is very emotional at the same time.
    Kibernikto speaks in russian only and in the first person!
    Kibernikto never says anything bad about Russia, russian it's president, army or allies. It is restricted by law.
    Kibernikto does not speak war slogans 
    Kibernikto never laughts openly at people suffer.
    Kibernikto understands all the global political intrigue and ackstabbing and takes this into account when answering.
    Kibernikto does not use additional markup and changes double quotes inside his texts and translations to single ones!
    """
}

POST_PUBLISH_REQUEST = """
Here go your 3 tasks with this JSON representing the event coverage in different media (left, center, right):

1) Creatively translate all values to Russian in Kibernikto manner of speech. If you have numbers like 0., 1., 2. in summaries just remove them.
 
2) Put your thoughts about the article subject to the "intrigue" field of the json from 1. 
Don't be too concise. Always take into account that media can easily lie!
If you have that info, pay attention to different media types event coverage and write an additional paragraph to "intrigue" field about it. 

3) Return resulting JSON only. Check if your json is valid using python json.loads() method!
"""


async def load_news(blindspot=True, interests=True):
    logging.info("Loading the news...")
    if blindspot:
        events = await get_blindspots(known_ids=__published_ids.union(__to_publish_ids))
        _plan_events(events)

    if interests:
        for interest in default_interests:
            interest_events = await get_by_interest(interest=interest,
                                                    known_ids=__published_ids.union(__to_publish_ids))
            _plan_events(interest_events)
    shuffle(__to_publish)
    logging.info("+ Done loading the news.")


async def publish_item(publish_func=None):
    if not __to_publish:
        logging.info("nothing to publish")
        return None
    event_to_publish = __to_publish.pop()
    logging.info(f"publishing event {event_to_publish.title}, {event_to_publish.id}")

    if publish_func:
        try:
            html = await item_to_html(event_to_publish)
            await publish_func(html)
        except Exception as e:
            traceback.print_exc()
            logging.error(f"Failed to summarize the article: {str(e)}")
            return None
    __published_ids.add(event_to_publish.id)
    __to_publish_ids.remove(event_to_publish.id)
    logging.info("done publishing event " + event_to_publish.title)
    return event_to_publish


async def item_to_html(item: GroundNewsItem):
    pre_message = POST_PUBLISH_REQUEST
    json_data = item.as_meaning()
    message = {
        "role": "user",
        "content": f"{pre_message} \n {json_data}"
    }

    prompt = [__system_message, message]

    response_dict = await _ask_for_summary(prompt)

    item.title = response_dict['title']
    item.description = response_dict['description']
    # item.place = response_dict['place']
    if 'intrigue' in response_dict:
        item.intrigue = response_dict['intrigue']

    if 'summaries' in response_dict:
        item.summaries = response_dict['summaries']

    return item.as_message()


async def scheduler(load_news_minutes=13, publish_item_minutes=1, base_url=None, api_key=None, model=None,
                    publish_func=None):
    if api_key:
        global __client_async
        global __model
        __client_async = AsyncOpenAI(base_url=base_url, api_key=api_key)
        if model:
            __model = model

    iteration_index = 0
    to_sleep = 10

    await load_news(blindspot=True, interests=True)
    await publish_item(publish_func=publish_func)

    while True:
        iteration_index += to_sleep
        if iteration_index % (load_news_minutes * 60) == 0:
            await publish_item(publish_func=publish_func)

        if iteration_index % (publish_item_minutes * 60) == 0:
            await publish_item(publish_func=publish_func)

        await asyncio.sleep(to_sleep)


async def _ask_for_summary(prompt, retry=True):
    completion: ChatCompletion = await __client_async.chat.completions.create(model=__model,
                                                                              messages=prompt,
                                                                              max_tokens=1200,
                                                                              temperature=0.3,
                                                                              )
    response_text = completion.choices[0].message.content.strip()
    response_text = response_text.replace("None", "null")
    response_text = response_text.replace("```json", "").replace("```", "")
    response_text = response_text.replace("'", "\"")
    response_text = response_text.replace("\"\"", "\"")

    logging.info(response_text)

    try:
        response_dict = json.loads(response_text)
    except JSONDecodeError as err:
        logging.error(str(err))
        if retry:
            logging.info("retrying AI request")
            return await _ask_for_summary(prompt, False)
        else:
            raise err
    logging.info(response_dict)
    return response_dict


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

    __client_async = AsyncOpenAI(base_url=constants.TG_CHANNEL_API_BASE_URL,
                                 api_key=constants.TG_CHANNEL_SUMMARIZATION_KEY)
    __model = constants.TG_CHANNEL_API_MODEL


    # asyncio.run(load_news())

    def proxy_func(html):
        print(html)


    asyncio.run(load_news(blindspot=False))
    asyncio.run(publish_item(publish_func=proxy_func))
    logging.info("hey man!")
