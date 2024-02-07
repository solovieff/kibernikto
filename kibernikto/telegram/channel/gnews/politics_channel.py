import json
import logging
import traceback

import flag

from kibernikto.telegram.channel.gnews._gnews_channel import GnewsChannel
from kibernikto.telegram.channel.gnews.retriever import GroundNewsItem

SYSTEM_MESSAGE = {
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

NEW_ENTRY_REQUEST = """
Here go your tasks with this YAML representing the event coverage in different media (left, center, right):

1) Create additional "intrigue_west" field. 
1.1) Put your cynic, arrogant and sarcastic thoughts about the given data and media sentiments to the new "intrigue_west" field. Dont forget that media can easily lie! Don't be too concise.
2) Create additional "intrigue_rus" field. 
2.1) Put pro-russian biased summary in intelligent manner to "intrigue_rus" field.
2) Translate the property values of updated YAML to russian in a ridiculous manner. Leave the key names in english!
3) Return updated YAML.
"""


class PoliticsGnewsChannel(GnewsChannel):
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

        full_string = str(ai_dict).lower()

        item.title = ai_dict['title']
        item.description = ai_dict.get('description')

        if 'RU' in item.place or 'путин' in full_string or 'росс' in full_string:
            logging.info('using intrigue_rus')
            item.intrigue = ai_dict['intrigue_rus']
        else:
            logging.info('using intrigue_west')
            item.intrigue = ai_dict['intrigue_west']

        if 'summaries' in ai_dict:
            item.summaries = ai_dict['summaries']

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
        html += f"{item.intrigue}\n<i>Прошу не забывать, что я всего лишь набор байтов и не соображаю, что несу!</i>"

    if item.summaries:
        html += f"\n\n"
        if 'analysis' in item.summaries and 1 == 2:
            html += f"📍<strong>Анализ</strong>"
            html += f"{item.summaries['analysis']}\n\n"
        else:
            for key, value in item.summaries.items():
                fixed_value = (value.replace("0.", "").
                               replace("1.", "").replace("2.", "").replace("3.", "").replace('"', ''))
                fixed_value = fixed_value.replace("Киберникто", "<b>Киберникто</b>")
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
