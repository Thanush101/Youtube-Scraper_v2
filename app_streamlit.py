import os

# Ensure Playwright and its dependencies are installed on Streamlit Cloud
# os.system("playwright install chromium")
# os.system("playwright install-deps")

import streamlit as st
import json
import os
from datetime import datetime

# --- Windows asyncio event loop fix for Playwright ---
import sys
if sys.platform.startswith("win"):
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from Youtube_scraperV3 import get_playlist_search_url, parse_duration
from playwright.sync_api import sync_playwright

# --- Helper function (refactored from Youtube_scraperV3.py) ---
def scrape_youtube_streamlit(course_name):
    # Improve English targeting in search
    modified_course_name = f"{course_name} English tutorial playlist"
    from Youtube_scraperV3 import get_playlist_search_url as orig_get_playlist_search_url
    def get_playlist_search_url(course_name):
        import urllib.parse
        encoded_course = urllib.parse.quote(modified_course_name)
        return f"https://www.youtube.com/results?search_query={encoded_course}&sp=EgIQAw%253D%253D"

    video_data = {
        "playlist_info": {},
        "videos": [],
        "metadata": {
            "scraped_at": datetime.now().isoformat(),
            "url": ""
        }
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            search_url = get_playlist_search_url(course_name)
            video_data["metadata"]["url"] = search_url
            page.goto(search_url)
            page.wait_for_load_state('networkidle')
            page.wait_for_load_state('domcontentloaded')
            # Wait for dynamic content
            import time
            time.sleep(3)
            # Try selectors for playlist
            selectors = [
                'ytd-item-section-renderer ytd-lockup-view-model a.yt-lockup-metadata-view-model-wiz__title',
                'ytd-item-section-renderer a#video-title',
                'ytd-item-section-renderer a[href*="/playlist?list="]',
                'ytd-item-section-renderer a[href*="&list="]'
            ]
            first_playlist = None
            for selector in selectors:
                try:
                    page.wait_for_selector(selector, timeout=5000)
                    first_playlist = page.locator(selector).first
                    if first_playlist.is_visible():
                        break
                except:
                    continue
            if not first_playlist:
                raise Exception("Could not find any playlist items")
            video_title = first_playlist.text_content()
            video_link = first_playlist.get_attribute('href')
            if not video_link or not ('/playlist?list=' in video_link or '&list=' in video_link):
                raise Exception("Invalid playlist link found")
            try:
                playlist_title = page.locator('#contents > yt-lockup-view-model:nth-child(2) > div > div > yt-lockup-metadata-view-model > div.yt-lockup-metadata-view-model-wiz__text-container > h3').text_content()
                video_data["playlist_info"]["title"] = playlist_title.strip()
            except:
                video_data["playlist_info"]["title"] = video_title.strip()
            first_playlist.click()
            page.wait_for_load_state('networkidle')
            page.wait_for_load_state('domcontentloaded')
            try:
                channel_name = page.locator('ytd-channel-name yt-formatted-string a').first.text_content()
                video_data["playlist_info"]["channel"] = channel_name.strip()
            except:
                video_data["playlist_info"]["channel"] = "Unknown Channel"
            video_data["playlist_info"]["url"] = f"https://www.youtube.com{video_link}"
            page.wait_for_selector('#contents ytd-playlist-video-renderer', timeout=10000)
            # Scroll to load all thumbnails
            last_height = page.evaluate('document.documentElement.scrollHeight')
            while True:
                page.evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
                time.sleep(2)
                new_height = page.evaluate('document.documentElement.scrollHeight')
                if new_height == last_height:
                    break
                last_height = new_height
            page.evaluate('window.scrollTo(0, 0)')
            time.sleep(1)
            video_items = page.locator('#contents ytd-playlist-video-renderer').all()
            for index, item in enumerate(video_items):
                try:
                    video_info = {}
                    title_element = item.locator('#video-title')
                    video_info["title"] = title_element.text_content().strip()
                    video_info["url"] = f"https://www.youtube.com{title_element.get_attribute('href')}"
                    try:
                        channel_element = item.locator('#channel-name #text')
                        video_info["channel"] = channel_element.text_content().strip()
                    except:
                        video_info["channel"] = video_data["playlist_info"]["channel"]
                    try:
                        thumbnail_element = item.locator('ytd-thumbnail img')
                        video_info["thumbnail"] = thumbnail_element.get_attribute('src')
                    except:
                        video_info["thumbnail"] = None
                    try:
                        duration_element = item.locator('ytd-thumbnail-overlay-time-status-renderer .badge-shape-wiz__text')
                        duration_text = duration_element.text_content().strip()
                        video_info["duration"] = duration_text
                        duration_seconds = parse_duration(duration_text)
                        if duration_seconds < 60:
                            continue
                    except:
                        video_info["duration"] = None
                        continue
                    try:
                        metadata_elements = item.locator('#metadata-line yt-formatted-string').all()
                        if len(metadata_elements) >= 2:
                            video_info["views"] = metadata_elements[0].text_content().strip()
                            video_info["upload_time"] = metadata_elements[1].text_content().strip()
                    except:
                        video_info["views"] = None
                        video_info["upload_time"] = None
                    video_data["videos"].append(video_info)
                except:
                    continue
            return video_data
        finally:
            browser.close()

# --- Streamlit UI ---
st.set_page_config(page_title="YouTube Playlist Scraper", layout="wide")
st.title("YouTube Playlist Scraper")
st.write("Enter a course name to search for related YouTube playlists and extract video details.")

course_name = st.text_input("Course Name", "")
run_btn = st.button("Scrape Playlist")

result_data = None
error = None

if run_btn and course_name.strip():
    with st.spinner("Scraping YouTube playlist... (this may take up to a minute)"):
        try:
            result_data = scrape_youtube_streamlit(course_name.strip())
        except Exception as e:
            error = str(e)

if error:
    st.error(f"Error: {error}")

if result_data:
    st.success("Scraping complete!")
    st.subheader("Playlist Information")
    st.json(result_data["playlist_info"])
    st.subheader("Videos")
    for vid in result_data["videos"]:
        with st.expander(vid.get("title", "No Title")):
            st.write(f"**URL**: {vid.get('url', 'N/A')}")
            st.write(f"**Channel**: {vid.get('channel', 'N/A')}")
            st.write(f"**Duration**: {vid.get('duration', 'N/A')}")
            st.write(f"**Views**: {vid.get('views', 'N/A')}")
            st.write(f"**Upload Time**: {vid.get('upload_time', 'N/A')}")
            if vid.get("thumbnail"):
                st.image(vid["thumbnail"], width=320)
    st.subheader("Download JSON")
    json_str = json.dumps(result_data, indent=2, ensure_ascii=False)
    st.download_button("Download Results as JSON", data=json_str, file_name=f"youtube_playlist_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", mime="application/json")
