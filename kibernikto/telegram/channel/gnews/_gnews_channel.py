import asyncio
import json
import logging
from abc import abstractmethod
from random import shuffle

import yaml
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from kibernikto.telegram.channel.gnews.retriever import get_main_events, get_blindspots, get_by_interest, GroundNewsItem


class GnewsChannel:
    type = "abstract"

    def __init__(self, api_key,
                 model="google/gemini-pro",
                 base_url="https://api.vsegpt.ru:6070/v1",
                 publish_func=None,
                 interests=['fashion'],
                 refresh_minutes=60,
                 new_pub_minutes=13,
                 system_message="",
                 order_string="",
                 ):
        self.refresh_minutes = refresh_minutes
        self.new_pub_minutes = new_pub_minutes

        self.model = model
        self.ai_client = AsyncOpenAI(base_url=base_url, api_key=api_key)

        self.publish_func = publish_func
        self.planned_publications = []
        self.planned_ids = set()
        self.published_ids = set()
        self.interests = interests
        self.system_message = system_message
        self.order_string = order_string

    async def start(self):
        iteration_index = 0
        to_sleep_seconds = 60

        #await self.load_data(main=True, interests=True, blindspot=True)
        #await self.safe_publication()

        while True:
            if iteration_index % (self.refresh_minutes * 60) == 0:
                await self.load_data(main=False, interests=True, blindspot=False)

            if iteration_index % (self.new_pub_minutes * 60) == 0:
                await self.safe_publication()

            iteration_index += to_sleep_seconds
            await asyncio.sleep(to_sleep_seconds)

    @property
    def known_ids(self):
        return self.planned_ids.union(self.published_ids)

    @property
    def chat_instance(self):
        return self.ai_client.chat.completions

    async def load_data(self, main=False, blindspot=False, interests=True):
        logging.info("~ loading the news ~")

        if main:
            events = await get_main_events(known_ids=self.known_ids)
            self._plan_events(events)

        if blindspot:
            events = await get_blindspots(known_ids=self.known_ids)
            self._plan_events(events)

        if interests:
            for interest in self.interests:
                interest_events = await get_by_interest(interest=interest,
                                                        known_ids=self.known_ids)
                self._plan_events(interest_events)
        shuffle(self.planned_publications)
        logging.info("+ Done loading the news +")

    async def safe_publication(self):
        try:
            return await self.make_publication()
        except Exception as e:
            logging.getLogger(__name__).error(e, exc_info=True)
            # logging.error(f"TG_CHANNEL: publication failed {e}")

    async def make_publication(self):
        """
        Generate a new publication for the channel and return the AI response as dict and event published.
        :return: dict
        """
        if not self.planned_publications:
            logging.warning("TG_CHANNEL: nothing to publish")
            return None, None
        event_to_publish = self.planned_publications.pop()
        logging.info(f"~ publishing event {event_to_publish.title}, {event_to_publish.id}")

        self.published_ids.add(event_to_publish.id)
        self.planned_ids.remove(event_to_publish.id)

        ai_string = await self._call_ai(event_to_publish)

        yaml_obj = yaml.safe_load(ai_string)
        json_str = json.dumps(yaml_obj)
        ai_dict = json.loads(json_str)

        return event_to_publish, ai_dict

    async def _call_ai(self, item: GroundNewsItem) -> str:
        yml_data = item.as_yaml()
        message = {
            "role": "user",
            "content": f"{self.order_string} \n {yml_data}"
        }

        prompt = [self.system_message, message]

        completion: ChatCompletion = await self.chat_instance.create(model=self.model,
                                                                     messages=prompt,
                                                                     max_tokens=1200,
                                                                     temperature=0.0,
                                                                     )
        response_text = completion.choices[0].message.content.strip()
        logging.info(f"\n\n{response_text}\n\n")
        return self._sanitize_response(response_text)

    def _plan_events(self, events):
        for event in events:
            self._add_to_queue(event)

    def _add_to_queue(self, news_item: GroundNewsItem, skip_duplicates=True):
        if skip_duplicates:
            if news_item.id in self.known_ids:
                logging.warning(f"{news_item.title} was already published or is planned")
                return

        self.planned_publications.append(news_item)
        self.planned_ids.add(news_item.id)

    def _sanitize_response(self, response_text: str):
        response_text = response_text.replace("```yaml", "")
        response_text = response_text.replace("```", "")
        response_text = response_text.replace("---", "")
        return response_text
