import asyncio
import collections
import json
import logging
from queue import Queue
from typing import List
from xml.sax.saxutils import quoteattr

import flag
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
        self.title = event['title'].replace("\"", "")
        self.description = event['description'].replace("\"", "")
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
            self.summaries = {}
            for key, value in event['chatGptSummaries'].items():
                self.summaries[key] = value.replace("\"", "")
        else:
            self.summaries = None

        self.intrigue = None

        self.sources = self.get_sources(event['firstTenSources'])
        self.place = self.get_place(event['place'])

        #

    @staticmethod
    def get_place(places_dicts: List):
        if places_dicts:
            places = []
            for pl in places_dicts:
                places.append(pl['id'])
            return places
        return None

    @staticmethod
    def get_sources(first_ten_sources):
        sources = []
        for src in first_ten_sources:
            if src['sourceInfo']['placeId']:
                place = f":{src['sourceInfo']['placeId'].split(',')[-1]}:"
            else:
                place = ':EARTH:'
            name = src['sourceInfo']['name'].split("[")[0]

            sources.append({
                "url": src['url'],
                "name": name,
                "bias": src['sourceInfo']['bias'],
                "place": place,
                "factuality": src['sourceInfo']['factuality'],
            })
        return sources

    def as_message(self):
        return _create_html_repr(self)

    def as_dict(self):
        return self.__dict__

    def as_meaning(self):
        meaning = {
            "title": self.title,
            "description": self.description,
            "place": self.place,
        }

        if self.summaries:
            meaning['summaries'] = self.summaries

        meaning['published_in_left_biased_sources'] = self.leftSrcCount
        meaning['published_in_right_biased_sources'] = self.rightSrcCount
        meaning['published_in_center_biased_sources'] = self.cntrSrcCount
        return meaning


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


def _create_html_repr(item: GroundNewsItem):
    html = ""
    if item.place is None:
        place = ""
    elif isinstance(item.place, collections.abc.Sequence):
        # place = ' / '.join(item.place)
        place = flag.flag(item.place[0])
    else:
        place = f'{flag.flag(item.place)}'

    html += f"<strong>{item.title}</strong> / {place}"
    if item.biasSourceCount:
        html += f"\n\n🗞<strong>Медиа-спектр</strong>:\n"
        html += f"<b>- Левые СМИ</b>: {item.leftSrcCount}\n"
        html += f"<b>- СМИ Оси</b>: {item.cntrSrcCount}\n"
        html += f"<b>- Правые СМИ</b>: {item.rightSrcCount}"
    if not item.summaries:
        html += f"\n\n<code>{item.description}</code>"
    # html += f"Количество публикаций: {item.biasSourceCount}"

    if item.intrigue:
        html += f"\n\n🏴‍☠️<strong>Мнение Киберникто</strong>\n"
        html += f"{item.intrigue}"

    if item.summaries:
        html += f"\n\n"
        if 'analysis' in item.summaries and 1 == 2:
            html += f"📍<strong>Анализ</strong>"
            html += f"{item.summaries['analysis']}\n\n"
        else:
            for key, value in item.summaries.items():
                fixed_value = (value.replace("0.", "").
                               replace("1.", "").replace("2.", "").replace("3.", "").replace('"', ''))
                fixed_value = fixed_value.replace("Киберникто", "\nКиберникто")
                if key == 'left':
                    icon = '🤦‍'
                    html += f"{icon}<b>Левые СМИ</b>:\n"
                elif key == 'center':
                    icon = '🧑‍⚖️'
                    html += f"{icon}<b>СМИ Оси</b>:\n"
                elif key == 'right':
                    icon = '🧑‍🚒'
                    html += f"{icon}<b>Правые СМИ</b>:\n"
                if key != 'analysis':
                    html += f"{fixed_value}\n"

    if item.sources and 1 == 1:
        if len(item.sources) == 1:
            html += "\n\n<b>Единственный источник: </b>"
            html += f'<a href="{item.sources[0]["url"]}">{item.sources[0]["name"]}</a> {flag.flag(item.sources[0]["place"])}'
        else:
            html += "\n\n<b>Источники</b> (возможны иноагенты и враги!)\n"
            for idx, src in enumerate(item.sources):
                html += f'<a href="{src["url"]}">{src["name"]}</a> {flag.flag(src["place"])} | '
                if idx > 6:
                    break
    html = html.replace("\"\"", "\"")
    print(html)
    return html


def main():
    # asyncio.run(get_ground_news_items('https://ground.news/interest/ukraine-politics'))
    # asyncio.run(get_ground_news_items('https://ground.news/blindspot'))
    # articles = asyncio.run(get_blindspots())
    articles = asyncio.run(get_by_interest())


if __name__ == '__main__':
    main()
