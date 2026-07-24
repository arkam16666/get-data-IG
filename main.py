from playwright.sync_api import sync_playwright
import json
import datetime
import time
import csv
def check_private_account(username):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state="instagram_session.json")
        page = context.new_page()
        
        profile_data = {}

        def handle_response(response):
            if 'graphql' in response.url:
                try:
                    data = response.json()
                    user = data.get('data', {}).get('user')
                    if user and 'is_private' in user:
                        profile_data['is_private'] = user['is_private']
                        reel = user.get('latest_reel_media')
                        profile_data['has_story'] = reel is not None and reel > 0
                        profile_data['followers'] = user.get('follower_count')
                        profile_data['following'] = user.get('following_count')
                        profile_data['posts'] = user.get('media_count')
                except Exception:
                    pass

        page.on('response', handle_response)

        try:
            page.goto(f'https://www.instagram.com/{username}/')
            page.wait_for_load_state('networkidle', timeout=15000)
            
            if 'is_private' in profile_data:
                is_private = profile_data['is_private']
                has_story = profile_data.get('has_story', False)
                followers = profile_data.get('followers')
                following = profile_data.get('following')
                posts = profile_data.get('posts')
                print(f"[{username}] Private: {is_private} | Story: {has_story} | Followers: {followers} | Following: {following} | Posts: {posts}")
                return {'username': username, 'is_private': is_private, 'has_story': has_story, 'followers': followers, 'following': following, 'posts': posts, 'method': 'API'}
            else:
                print(f"{username} - Could not extract is_private")
                return {'username': username, 'is_private': None, 'method': 'Failed'}
                
        except Exception as e:
            print(f"{username} - Error: {str(e)}")
            return {'username': username, 'error': str(e)}
        finally:
            browser.close()

username = 'User Name'  # Replace with the actual username you want to check
with open("data.csv", "a", newline="", encoding="utf-8") as f:
    
    writer = csv.writer(f)
    writer.writerow([
        "Date",
        "Time",
        "Private",
        "Story",
        "Followers",
        "Following",
        "Posts"
    ])
    while True:
        x = datetime.datetime.now()
        a = check_private_account(username)

        if 'has_story' not in a:
            print(f"Skipping write — incomplete data: {a}")
            print("*"*200)
            time.sleep(60)
            continue

        print(
            x.strftime("%Y-%m-%d %H:%M:%S"),
            a['is_private'],
            a['has_story'],
            a['followers'],
            a['following'],
            a['posts']
        )

        writer.writerow([
            x.strftime("%Y-%m-%d"),
            x.strftime("%H:%M:%S"),
            a['is_private'],
            a['has_story'],
            a['followers'],
            a['following'],
            a['posts']
        ])
        f.flush()
        print("*"*200)
        time.sleep(60)