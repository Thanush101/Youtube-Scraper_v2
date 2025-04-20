import logging
from playwright.sync_api import sync_playwright
import time
import json
from datetime import datetime
import urllib.parse
import argparse
import os

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)

def get_playlist_search_url(course_name):
    # Append " in English" to enforce language filtering
    modified_course_name = f"{course_name} in English"
    encoded_course = urllib.parse.quote(modified_course_name)
    
    # Use the search filter that prioritizes playlists
    return f"https://www.youtube.com/results?search_query={encoded_course}&sp=EgIQAw%253D%253D"

def parse_duration(duration_text):
    """Convert YouTube duration text (HH:MM:SS or MM:SS) to total seconds."""
    try:
        parts = duration_text.split(':')
        if len(parts) == 2:  # Format MM:SS
            minutes, seconds = map(int, parts)
            return minutes * 60 + seconds
        elif len(parts) == 3:  # Format HH:MM:SS
            hours, minutes, seconds = map(int, parts)
            return hours * 3600 + minutes * 60 + seconds
        return 0  # Default case if format is unexpected
    except Exception as e:
        log.warning(f"Failed to parse duration '{duration_text}': {e}")
        return 0

def save_to_json(data, output_dir="output"):
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate filename with timestamp
    filename = f"youtube_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(output_dir, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    log.debug(f"Data saved to {filepath}")
    return filepath

def scrape_youtube(course_name, output_dir="output"):
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
            # Get the playlist search URL
            search_url = get_playlist_search_url(course_name)
            video_data["metadata"]["url"] = search_url
            
            # Navigate directly to the playlist search results
            page.goto(search_url)
            
            # Wait for the page to load completely
            page.wait_for_load_state('networkidle')
            page.wait_for_load_state('domcontentloaded')
            
            # Wait a bit for dynamic content to load
            time.sleep(3)
            
            # Try different selectors for playlist items
            selectors = [
                'ytd-item-section-renderer ytd-lockup-view-model a.yt-lockup-metadata-view-model-wiz__title',
                'ytd-item-section-renderer a#video-title',
                'ytd-item-section-renderer a[href*="/playlist?list="]',
                'ytd-item-section-renderer a[href*="&list="]'
            ]
            
            first_playlist = None
            for selector in selectors:
                try:
                    log.debug(f"Trying selector: {selector}")
                    # Wait for any element matching the selector
                    page.wait_for_selector(selector, timeout=5000)
                    first_playlist = page.locator(selector).first
                    if first_playlist.is_visible():
                        log.debug(f"Found playlist with selector: {selector}")
                        break
                except Exception as e:
                    log.debug(f"Selector {selector} failed: {e}")
                    continue
            
            if not first_playlist:
                raise Exception("Could not find any playlist items")
            
            # Get playlist information
            video_title = first_playlist.text_content()
            video_link = first_playlist.get_attribute('href')
            
            # Ensure we have a valid link
            if not video_link or not ('/playlist?list=' in video_link or '&list=' in video_link):
                raise Exception("Invalid playlist link found")
            
            # Get playlist title from search results using the correct selector
            try:
                playlist_title = page.locator('#contents > yt-lockup-view-model:nth-child(2) > div > div > yt-lockup-metadata-view-model > div.yt-lockup-metadata-view-model-wiz__text-container > h3').text_content()
                video_data["playlist_info"]["title"] = playlist_title.strip()
                log.debug(f"Found playlist title: {playlist_title}")
            except Exception as e:
                log.warning(f"Could not get playlist title from search results: {e}")
                video_data["playlist_info"]["title"] = video_title.strip()
            
            # Click the playlist
            first_playlist.click()
            
            # Wait for video page to load
            page.wait_for_load_state('networkidle')
            page.wait_for_load_state('domcontentloaded')
            
            # Get channel name
            try:
                channel_name = page.locator('ytd-channel-name yt-formatted-string a').first.text_content()
                video_data["playlist_info"]["channel"] = channel_name.strip()
            except Exception as e:
                log.warning(f"Could not get channel name: {e}")
                video_data["playlist_info"]["channel"] = "Unknown Channel"
            
            # Store playlist URL with full URL construction
            video_data["playlist_info"]["url"] = f"https://www.youtube.com{video_link}"
            
            # Wait for playlist videos to load
            page.wait_for_selector('#contents ytd-playlist-video-renderer', timeout=10000)
            
            # Scroll to load all thumbnails
            log.debug("Starting to scroll to load all thumbnails...")
            last_height = page.evaluate('document.documentElement.scrollHeight')
            while True:
                # Scroll down
                page.evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
                # Wait for new content to load
                time.sleep(2)
                
                # Calculate new scroll height
                new_height = page.evaluate('document.documentElement.scrollHeight')
                
                # Break if no more new content (height didn't change)
                if new_height == last_height:
                    break
                    
                last_height = new_height
                log.debug(f"Scrolled to height: {new_height}")
            
            # Scroll back to top
            page.evaluate('window.scrollTo(0, 0)')
            time.sleep(1)  # Wait for any final loading
            
            # Get all playlist videos
            video_items = page.locator('#contents ytd-playlist-video-renderer').all()
            log.debug(f"Found {len(video_items)} videos in playlist")
            
            # Extract information for each video
            for index, item in enumerate(video_items):
                try:
                    video_info = {}
                    
                    # Get video title
                    title_element = item.locator('#video-title')
                    video_info["title"] = title_element.text_content().strip()
                    video_info["url"] = f"https://www.youtube.com{title_element.get_attribute('href')}"
                    
                    # Get channel name
                    try:
                        channel_element = item.locator('#channel-name #text')
                        video_info["channel"] = channel_element.text_content().strip()
                    except:
                        video_info["channel"] = video_data["playlist_info"]["channel"]
                    
                    # Get thumbnail
                    try:
                        thumbnail_element = item.locator('ytd-thumbnail img')
                        video_info["thumbnail"] = thumbnail_element.get_attribute('src')
                    except:
                        video_info["thumbnail"] = None
                    
                    # Get duration
                    try:
                        duration_element = item.locator('ytd-thumbnail-overlay-time-status-renderer .badge-shape-wiz__text')
                        duration_text = duration_element.text_content().strip()
                        video_info["duration"] = duration_text
                        
                        # Parse duration and filter videos
                        duration_seconds = parse_duration(duration_text)
                        if duration_seconds < 60 :
                            log.debug(f"Skipping video '{video_info['title']}' due to duration: {duration_text}")
                            continue
                            
                    except Exception as e:
                        log.warning(f"Failed to get duration: {e}")
                        video_info["duration"] = None
                        continue  # Skip videos without duration
                    
                    # Get metadata (views and upload time)
                    try:
                        metadata_elements = item.locator('#metadata-line yt-formatted-string').all()
                        if len(metadata_elements) >= 2:
                            video_info["views"] = metadata_elements[0].text_content().strip()
                            video_info["upload_time"] = metadata_elements[1].text_content().strip()
                    except:
                        video_info["views"] = None
                        video_info["upload_time"] = None
                    
                    video_data["videos"].append(video_info)
                    
                    # Scroll after every 6th video
                    if (index + 1) % 6 == 0 and index < len(video_items) - 1:
                        log.debug(f"Scrolling after video {index + 1}")
                        # Scroll to the next video
                        item.scroll_into_view_if_needed()
                        time.sleep(1)  # Wait for thumbnail to load
                    
                except Exception as e:
                    log.warning(f"Failed to extract video info: {e}")
                    continue
            
            # Print formatted data
            print("\nPlaylist Information:")
            print(json.dumps(video_data, indent=2, ensure_ascii=False))
            
            # Save to JSON file
            output_file = save_to_json(video_data, output_dir)
            print(f"\nData saved to: {output_file}")
            
            # Wait for demo purposes
            page.wait_for_timeout(5000)
            
        except Exception as e:
            log.error(f"Error: {e}")
            raise e
        finally:
            browser.close()

def main():
    parser = argparse.ArgumentParser(description='YouTube Playlist Scraper')
    parser.add_argument('course_name', type=str, help='Name of the course to search for')
    parser.add_argument('--output-dir', type=str, default='output', help='Directory to save JSON output (default: output)')
    parser.add_argument('--headless', action='store_true', help='Run browser in headless mode')
    
    args = parser.parse_args()
    
    try:
        print(f"\nSearching for: {args.course_name}")
        print(f"Output directory: {args.output_dir}")
        print("Starting scraper...\n")
        
        scrape_youtube(args.course_name, args.output_dir)
        
    except Exception as e:
        print(f"\nError: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main()) 