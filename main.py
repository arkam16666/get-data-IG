from playwright.sync_api import sync_playwright
import datetime
import time
import csv
import os

USERNAME = 'your_instagram_username'  # เปลี่ยนเป็นชื่อผู้ใช้ Instagram ของคุณ
CHECK_INTERVAL = 300  # วินาที (5 นาที)

DATA_CSV             = 'data.csv'
FOLLOWERS_CSV        = f'followers_{USERNAME}.csv'
FOLLOWING_CSV        = f'following_{USERNAME}.csv'
FOLLOWERS_CHANGES    = f'followers_changes_{USERNAME}.csv'
FOLLOWING_CHANGES    = f'following_changes_{USERNAME}.csv'

# ── CSV helpers ──────────────────────────────────────────────────────────────

def csv_has_header(path):
    """คืน True ถ้าไฟล์มีอยู่และมีเนื้อหา (มี header แล้ว)"""
    if not os.path.exists(path):
        return False
    with open(path, 'r', encoding='utf-8-sig') as f:
        return f.readline().strip() != ''

def append_csv(path, fieldnames, rows):
    """เพิ่มข้อมูลลง CSV สร้าง header ก็ต่อเมื่อยังไม่มี"""
    write_header = not csv_has_header(path)
    with open(path, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)

def load_follow_list(path):
    """โหลดรายชื่อจาก CSV คืนเป็น dict {username: row}"""
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8-sig') as f:
        return {row['username']: row for row in csv.DictReader(f)}

def save_follow_list(path, users):
    """บันทึกรายชื่อเต็มลง CSV (overwrite ทุกครั้ง)"""
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=['username', 'full_name', 'is_private', 'pk'])
        writer.writeheader()
        writer.writerows(users)

# ── Instagram API ─────────────────────────────────────────────────────────────

def fetch_follow_list(context, user_id, username, list_type, expected_count=None):
    """ดึง followers หรือ following ทั้งหมดผ่าน Instagram API
    คืน (list, is_complete) โดย is_complete=True เมื่อดึงได้ครบตามที่คาดไว้"""
    result, next_max_id, page_num = [], None, 1
    headers = {
        'x-ig-app-id': '936619743392459',
        'x-requested-with': 'XMLHttpRequest',
        'referer': f'https://www.instagram.com/{username}/',
    }
    while True:
        url = f'https://www.instagram.com/api/v1/friendships/{user_id}/{list_type}/?count=200'
        if next_max_id:
            url += f'&max_id={next_max_id}'
        try:
            resp = context.request.get(url, headers=headers)
            data = resp.json()
        except Exception as e:
            print(f"  [✗] Request error ({list_type}): {e}")
            return result, False
        if not resp.ok:
            print(f"  [✗] HTTP {resp.status} ({list_type}): {data}")
            return result, False
        users = data.get('users', [])
        seen = {u['username'] for u in result}
        for u in users:
            uname = u.get('username')
            if uname and uname not in seen:  # ป้องกัน duplicate จาก cursor ที่ซ้อนกัน
                result.append({'username': uname, 'full_name': u.get('full_name'),
                               'is_private': u.get('is_private'), 'pk': u.get('pk')})
                seen.add(uname)
        next_max_id = data.get('next_max_id')
        print(f"  [{list_type}] หน้า {page_num}: {len(users)} รายการ (รวม {len(result)})")
        page_num += 1
        if not next_max_id or not users:
            break
        time.sleep(2)

    # ตรวจความครบถ้วน
    # Instagram นับรวมบัญชีที่ลบ/ระงับ/block ใน follower_count แต่ API ไม่คืนมา
    # ดังนั้นยอมรับได้ถึง 85% (ถ้าต่ำกว่านี้คือ pagination พัง ไม่ใช่แค่บัญชีไม่ active)
    if expected_count and expected_count > 0:
        ratio = len(result) / expected_count
        print(f"  [{list_type}] ดึงได้ {len(result)}/{expected_count} ({ratio:.0%})")
        if ratio < 0.85:
            print(f"  [⚠] ได้ข้อมูลน้อยกว่า 85% — pagination อาจพัง ข้ามการเปรียบเทียบรอบนี้")
            return result, False
    return result, True

# ── Main check ────────────────────────────────────────────────────────────────

def check_and_update(username):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state="instagram_session.json")
        page = context.new_page()

        profile_data = {}
        user_id = None

        def handle_response(response):
            nonlocal user_id
            if 'graphql' in response.url or '/api/v1/users/web_profile_info' in response.url:
                try:
                    data = response.json()
                    user = (data.get('data', {}).get('user') or
                            data.get('graphql', {}).get('user'))
                    if user:
                        if user.get('id') and not user_id:
                            user_id = user['id']
                        if 'is_private' in user:
                            profile_data['is_private']  = user['is_private']
                            reel = user.get('latest_reel_media')
                            profile_data['has_story']   = reel is not None and reel > 0
                            profile_data['followers']   = user.get('follower_count')
                            profile_data['following']   = user.get('following_count')
                            profile_data['posts']       = user.get('media_count')
                except Exception:
                    pass

        page.on('response', handle_response)

        try:
            page.goto(f'https://www.instagram.com/{username}/', wait_until='networkidle', timeout=20000)
        except Exception as e:
            print(f"[✗] โหลดหน้าไม่ได้: {e}")
            browser.close()
            return

        now = datetime.datetime.now()

        if 'is_private' not in profile_data:
            print(f"[✗] ดึงข้อมูลโปรไฟล์ไม่ได้ — อาจ session หมดอายุ")
            browser.close()
            return

        is_private      = profile_data['is_private']
        has_story       = profile_data.get('has_story', False)
        followers_count = profile_data.get('followers')
        following_count = profile_data.get('following')
        posts           = profile_data.get('posts')

        print(f"[{username}] Private: {is_private} | Story: {has_story} | "
              f"Followers: {followers_count} | Following: {following_count} | Posts: {posts}")

        # บันทึกสถิติลง data.csv (เช็ค header ก่อนเสมอ)
        append_csv(DATA_CSV,
                   ['Date', 'Time', 'Private', 'Story', 'Followers', 'Following', 'Posts'],
                   [{'Date': now.strftime('%Y-%m-%d'), 'Time': now.strftime('%H:%M:%S'),
                     'Private': is_private, 'Story': has_story,
                     'Followers': followers_count, 'Following': following_count, 'Posts': posts}])

        # ถ้า Private → รอ ไม่ดึงรายชื่อ
        if is_private:
            print(f"[⚠] บัญชีเป็น Private — ข้ามการดึง Followers/Following รอจนกว่าจะเป็น Public")
            browser.close()
            return

        # Public → ดึงรายชื่อและเปรียบเทียบ
        if not user_id:
            print("[✗] ไม่พบ user_id — ข้ามการดึงรายชื่อ")
            browser.close()
            return

        print(f"\n[→] ดึงรายชื่อ Followers และ Following...")
        new_followers, f_complete  = fetch_follow_list(context, user_id, username, 'followers', followers_count)
        new_following, fg_complete = fetch_follow_list(context, user_id, username, 'following', following_count)
        browser.close()

        # โหลดรายชื่อเดิม
        prev_followers = load_follow_list(FOLLOWERS_CSV)
        prev_following = load_follow_list(FOLLOWING_CSV)

        new_f_set  = {u['username'] for u in new_followers}
        new_fg_set = {u['username'] for u in new_following}
        new_f_map  = {u['username']: u for u in new_followers}
        new_fg_map = {u['username']: u for u in new_following}

        ts = {'date': now.strftime('%Y-%m-%d'), 'time': now.strftime('%H:%M:%S')}
        change_fields = ['date', 'time', 'type', 'username', 'full_name']

        # ── Followers changes ──
        if not f_complete:
            print("  [⚠] Followers ข้ามการเปรียบเทียบ — ดึงข้อมูลไม่ครบ")
        elif prev_followers:
            joined  = new_f_set - set(prev_followers)
            left    = set(prev_followers) - new_f_set
            changes = []
            for u in sorted(joined):
                info = new_f_map.get(u, {})
                changes.append({**ts, 'type': 'new',     'username': u, 'full_name': info.get('full_name', '')})
                print(f"  [+] Follower ใหม่:  @{u}")
            for u in sorted(left):
                info = prev_followers.get(u, {})
                changes.append({**ts, 'type': 'removed', 'username': u, 'full_name': info.get('full_name', '')})
                print(f"  [-] Follower หาย:  @{u}")
            if changes:
                append_csv(FOLLOWERS_CHANGES, change_fields, changes)
            else:
                print("  [=] Followers ไม่มีการเปลี่ยนแปลง")
        else:
            print(f"  [ℹ] บันทึก Followers ครั้งแรก ({len(new_followers)} คน)")

        # ── Following changes ──
        if not fg_complete:
            print("  [⚠] Following ข้ามการเปรียบเทียบ — ดึงข้อมูลไม่ครบ")
        elif prev_following:
            joined  = new_fg_set - set(prev_following)
            left    = set(prev_following) - new_fg_set
            changes = []
            for u in sorted(joined):
                info = new_fg_map.get(u, {})
                changes.append({**ts, 'type': 'new',     'username': u, 'full_name': info.get('full_name', '')})
                print(f"  [+] Following ใหม่: @{u}")
            for u in sorted(left):
                info = prev_following.get(u, {})
                changes.append({**ts, 'type': 'removed', 'username': u, 'full_name': info.get('full_name', '')})
                print(f"  [-] Following หาย: @{u}")
            if changes:
                append_csv(FOLLOWING_CHANGES, change_fields, changes)
            else:
                print("  [=] Following ไม่มีการเปลี่ยนแปลง")
        else:
            print(f"  [ℹ] บันทึก Following ครั้งแรก ({len(new_following)} คน)")

        # บันทึก snapshot ใหม่เฉพาะเมื่อดึงได้ครบ
        if f_complete:
            save_follow_list(FOLLOWERS_CSV, new_followers)
        if fg_complete:
            save_follow_list(FOLLOWING_CSV, new_following)

        print(f"\n📊 [{now.strftime('%H:%M:%S')}] Followers: {len(new_followers)} | Following: {len(new_following)}")

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print(f"🚀 เริ่มติดตาม @{USERNAME}  (ทุก {CHECK_INTERVAL//60} นาที)")
    print("=" * 60)
    while True:
        try:
            check_and_update(USERNAME)
        except Exception as e:
            print(f"[Error] {e}")
        print("=" * 60)
        print(f"⏳ รอ {CHECK_INTERVAL//60} นาที...")
        time.sleep(CHECK_INTERVAL)