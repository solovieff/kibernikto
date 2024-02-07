import json
import logging
import traceback

import flag

from kibernikto.telegram.channel.gnews._gnews_channel import GnewsChannel
from kibernikto.telegram.channel.gnews.retriever import GroundNewsItem

SYSTEM_MESSAGE = {
    'role': 'system',
    'content': """
    You're Kibernikto, a cool designer girl from Southern London. 
    Kibernikto speaks russian only always and in the first person! If she sees another language -- he translates to russian.
    Kibernikto speaks arrogant and pretentious. 
    Kibernikto is an expert on fashion, exotic foods and all things sophisticated. 
    Kibernikto has a subtle sense of humor.
    """
}

NEW_ENTRY_REQUEST = """
Here go your tasks with this YAML representing the event coverage in media:

1) Create additional "intrigue" field. 
1.1) Put your cynic, arrogant and sarcastic personal opinion on the event to the new "intrigue" field. Don't be too concise and too kind.
1.2) Add a couple of abstract thoughts about article topic to the "intrigue" field separated by linebreak. 
2) Translate the property values of updated YAML to russian in a battle rap manner. Leave the key names in english!
3) Check the result YAML according to YAML rules and fix possible quoting or column issues.
3.1) Return result data YAML only.
"""


class FreeGnewsChannel(GnewsChannel):
    type = "politics"

    def __init__(self, api_key: str,
                 model="google/gemini-pro",
                 base_url="https://api.vsegpt.ru:6070/v1",
                 publish_func=None,
                 interests=['fashion'],
                 refresh_minutes=60,
                 new_pub_minutes=13):

        super().__init__(api_key,
                         model=model,
                         base_url=base_url,
                         publish_func=publish_func,
                         interests=interests,
                         refresh_minutes=refresh_minutes,
                         new_pub_minutes=new_pub_minutes,
                         system_message=SYSTEM_MESSAGE,
                         order_string=NEW_ENTRY_REQUEST)

    async def make_publication(self):
        item, ai_dict = await super().make_publication()
        if not item:
            return None

        logging.info(f"~ publishing event {item.title}, {item.id}")

        item.title = ai_dict['title']
        item.description = ai_dict.get('description')
        item.intrigue = ai_dict['intrigue']

        if self.publish_func:
            html = _item_to_html(item)
            await self.publish_func(html)
        logging.info(f"+ done publishing event {item.title}, {item.id}")
        return item, ai_dict


def _item_to_html(item: GroundNewsItem):
    html = ""
    if item.place is None:
        place = '👽'
    try:
        place = flag.flag(item.place)
    except Exception as e:
        place = '👽'

    html += f"<strong>{item.title}</strong> / {place}"
    html += f"\n\n<code>{item.description}</code>"
    if item.intrigue:
        html += f"\n\n🏴‍☠️<strong>Мнение Киберникто</strong>\n"
        html += f"{item.intrigue}\n<i>Прошу не забывать, что я всего лишь набор байтов и не соображаю, что несу!</i>"

    if item.sources and 1 == 1:
        if len(item.sources) == 1:
            src = item.sources[0]
            try:
                flag_icon = flag.flag(src["place"])
            except ValueError as e:
                flag_icon = '👽'
            html += "\n\n<b>Единственный источник: </b>"
            html += f'<a href="{src["url"]}">{src["name"]}</a> {flag_icon}'
        else:
            html += "\n\n<b>Источники</b> (возможны иноагенты и враги!)\n"
            for idx, src in enumerate(item.sources):
                try:
                    flag_icon = flag.flag(src["place"])
                except Exception as e:
                    flag_icon = '👽'
                html += f'<a href="{src["url"]}">{src["name"]}</a> {flag_icon} | '
                if idx > 6:
                    break
    html = html.replace("```json", "").replace("```", "")
    html = html.replace("\"\"", "\"")
    html = html.replace(": \"", ":\"")
    html = html.replace(" \"", "")
    html = html.replace("\" ", "")
    html = html.replace("\".", "")
    html = html.replace("None", "null")

    print(html)
    return html
