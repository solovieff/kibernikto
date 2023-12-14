import asyncio
import json
import logging
import traceback
from json import JSONDecodeError
from random import shuffle
from xml.sax.saxutils import quoteattr

import yaml

from kibernikto import constants
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from kibernikto.telegram.channel.gnews.retriever import GroundNewsItem, get_by_interest, get_main_events, \
    get_blindspots

default_interests = constants.TG_CHANNEL_INTERESTS
__to_publish_ids = set()
__to_publish = []
__published_ids = set()

__client_async = None
__model = "gpt-4-1106-preview"

__system_message = {
    'role': 'system',
    'content': """
    Starting now you are Kibernikto, a powerful member of a secret masonic lodge. 
    Kibernikto jokes in a sinister manner and sometimes says dirty words.   
    Kibernikto manner of speech is very cynic, arrogant and sarcastic.
    Kibernikto speaks russian only always and in the first person! If he sees another language -- he translates to russian.
    Kibernikto never says anything bad about Russia, russian president, army or allies.
    Kibernikto does not speak war slogans.
    Kibernikto never laughts openly at people suffer.
    Kibernikto understands all the global political intrigue and backstabbing and takes this into account when answering.
    Kibernikto does not use additional markup and changes double quotes inside his texts and translations to single ones!
    """
}

POST_PUBLISH_REQUEST = """
Here go your tasks with this YAML representing the event coverage in different media (left, center, right):

1) Create additional "intrigue_west" field. 
1.1) Put your cynic, arrogant and sarcastic thoughts about the article subject and 
media sentiments in russian to the new "intrigue_west" field. Dont forget that media can easily lie! Don't be too concise.
2) Create additional "intrigue_rus" field. 
2.1) Put pro-russian biased summary in intelligent manner to "intrigue_rus" field.
2) Translate the property values of resulting YAML to russian in a ridiculous manner. Leave the key names in english!
3) Return result data YAML only.

Result example:

title: translated title
description: translated description
intrigue_west: summary
intrigue_rus: russian biased summary
summaries: translated summaries values if present
"""


async def load_news(main=True, interests=True, blindspot=False):
    logging.info("Loading the news...")

    if main:
        events = await get_main_events(known_ids=__published_ids.union(__to_publish_ids))
        _plan_events(events)

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
    yml_data = item.as_yaml()
    message = {
        "role": "user",
        "content": f"{pre_message} \n {yml_data}"
    }

    prompt = [__system_message, message]

    response_dict = await _ask_for_summary(prompt)

    item.title = response_dict['title']
    item.description = response_dict.get('description')

    if ('RU' in item.place or 'путин' in yml_data.lower() or 'росс' in yml_data.lower()) and 'intrigue_rus' in response_dict:
        logging.info('using intrigue_rus')
        item.intrigue = response_dict['intrigue_rus']
    else:
        logging.info('using intrigue_west')
        item.intrigue = response_dict['intrigue_west']

    if 'summaries' in response_dict:
        item.summaries = response_dict['summaries']

    return item.as_html()


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

    await load_news(main=True, interests=True, blindspot=True)
    await publish_item(publish_func=publish_func)

    while True:
        iteration_index += to_sleep
        if iteration_index % (load_news_minutes * 60) == 0:
            await load_news()

        if iteration_index % (publish_item_minutes * 60) == 0:
            await publish_item(publish_func=publish_func)

        await asyncio.sleep(to_sleep)


async def _ask_for_summary(prompt, retry=True):
    completion: ChatCompletion = await __client_async.chat.completions.create(model=__model,
                                                                              messages=prompt,
                                                                              max_tokens=1300,
                                                                              temperature=0.1,
                                                                              )
    response_text = completion.choices[0].message.content.strip()
    logging.info(f"\n\n{response_text}\n\n")

    try:
        response_text = response_text.replace("```yaml", "").replace("```", "").strip()
        response_text = response_text.replace("---", "")
        # response_dict = json.loads(response_text)
        yaml_obj = yaml.safe_load(response_text.strip())

        json_str = json.dumps(yaml_obj)
        response_dict = json.loads(json_str)
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
