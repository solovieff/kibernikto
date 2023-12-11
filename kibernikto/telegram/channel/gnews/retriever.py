import asyncio
import json
import logging
import pprint
from queue import Queue
from typing import List

from bs4 import BeautifulSoup
from pydantic import HttpUrl

from kibernikto.utils.text import get_website_html

DEFAULT_URL = 'https://ground.news'

__to_publish = Queue()
__published = []

ARTICLE_URL = """{DEFAULT_URL}/article/{slug}"""


class GroundNewsItem():
    def __init__(self, event: dict):
        self.id = event['id']
        self.slug = event['slug']
        self.url = ARTICLE_URL.format(DEFAULT_URL=DEFAULT_URL, slug=self.slug)
        self.title = event['title']
        self.description = event['description']
        self.start = event['start']

        # left right distribution
        self.biasSourceCount = event['biasSourceCount']
        self.leftSrcPercent = event['leftSrcPercent']
        self.rightSrcPercent = event['rightSrcPercent']
        self.leftSrcCount = event['leftSrcCount']
        self.rightSrcCount = event['rightSrcCount']
        self.cntrSrcCount = event['cntrSrcCount']

        # fact check distribution
        self.highFactPercent = event['highFactPercent']
        self.lowFactPercent = event['lowFactPercent']
        self.mixedFactPercent = event['mixedFactPercent']

        # tags
        # self.tags = event['interests']

        if 'chatGptSummaries' in event:
            self.summaries = event['chatGptSummaries']
        else:
            self.summaries = None

        self.sources = self.get_sources(event['firstTenSources'])
        self.place = self.get_place(event['place'])

        #

    @staticmethod
    def get_place(places_dicts: List):
        if places_dicts:
            places = []
            for pl in places_dicts:
                places.append(pl['name'])
            return places
        return None

    @staticmethod
    def get_sources(first_ten_sources):
        sources = []
        for src in first_ten_sources:
            sources.append({
                "url": src['url'],
                "name": src['sourceInfo']['name'],
                "bias": src['sourceInfo']['bias'],
                "country": src['sourceInfo']['placeId'],
                "factuality": src['sourceInfo']['factuality'],
            })
        return sources

    def as_message(self):
        return f"<strong>{self.title}</strong> \n\n {self.description} \n<strong>{self.place}</strong>"

    def as_dict(self):
        return self.__dict__


def set_tags():
    pass


async def get_ground_news_items(url: HttpUrl):
    html = await get_website_html(url)
    # print(html)
    soup = BeautifulSoup(html, "html.parser")

    # find the script tag with the id "__NEXT_DATA__"
    script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
    if script_tag:
        # parse json content
        data = json.loads(script_tag.string)
        logging.info(f"loaded pageProps for {url}")
        return data['props']['pageProps']
    else:
        return None


async def get_article_data(article_url: HttpUrl):
    spot_data = await get_ground_news_items(article_url)
    if 'event' not in spot_data:
        logging.error("no event data for " + article_url)
        return None
    article_event = spot_data['event']
    item = GroundNewsItem(event=article_event)
    logging.info(f"loaded {item.title} article")
    return item


async def get_blindspots(known_ids=[]):
    page_props = await get_ground_news_items('https://ground.news/blindspot')
    left_blind_spots = page_props['leftBlindspots']
    right_blind_spots = page_props['rightBlindspots']

    articles = []

    for spot in (left_blind_spots + right_blind_spots):
        if spot['id'] in known_ids:
            continue
        url = ARTICLE_URL.format(DEFAULT_URL=DEFAULT_URL, slug=spot['slug'])
        # url = f"{DEFAULT_URL}/article/{spot['slug']}"
        spot_data = await get_article_data(url)
        if spot_data:
            articles.append(spot_data)
            await asyncio.sleep(0.5)
    return articles


async def get_by_interest(interest: str = 'ukraine-crisis', known_ids=[]):
    page_props = await get_ground_news_items(f'{DEFAULT_URL}/interest/{interest}')
    events = page_props['events']

    articles = []
    for spot in events:
        if spot['id'] in known_ids:
            continue
        url = f"{DEFAULT_URL}/article/{spot['slug']}"
        spot_data = await get_article_data(url)
        if spot_data:
            articles.append(spot_data)
            await asyncio.sleep(1)

    return articles


def main():
    # asyncio.run(get_ground_news_items('https://ground.news/interest/ukraine-politics'))
    # asyncio.run(get_ground_news_items('https://ground.news/blindspot'))
    # articles = asyncio.run(get_blindspots())
    articles = asyncio.run(get_by_interest())


if __name__ == '__main__':
    main()
