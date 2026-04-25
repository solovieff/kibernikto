import logging
import os

import aiohttp

URL = 'https://api.imgbb.com/1/upload'

IMAGE_STORAGE_API_KEY = os.environ.get('IMAGE_STORAGE_API_KEY', "d581d52610fc664c1d632cbeb8362686")


async def post(filename, name):
    """Post using a filename like 'image.jpg'"""
    with open(filename, 'rb') as img:
        payload = {"key": IMAGE_STORAGE_API_KEY, "image": img.read(), "name": name}
        async with aiohttp.ClientSession() as session:
            async with session.post(URL, data=payload) as response:
                resp = await response.json()
    return resp


async def publish_image_file(image_bytes, name):
    try:
        url = "https://api.imgbb.com/1/upload"
        payload = {'key': IMAGE_STORAGE_API_KEY, 'image': image_bytes, 'name': name, 'expiration': '300'}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=payload) as response:
                resp = await response.json()
                if response.status == 200:
                    return resp['data']['url']
                else:
                    logging.error(f"Image upload failed: {resp}")
                    return None
    except Exception as e:
        logging.error(f"Image upload failed: {str(e)}")
        return None
