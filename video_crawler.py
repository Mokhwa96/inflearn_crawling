from seleniumwire import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.common import exceptions as selenium_exceptions
import time, os
import requests
import re
from urllib.parse import urlsplit, quote_from_bytes
import subprocess
import shutil
import base64
try:
    from Crypto.Cipher import AES
except Exception:
    AES = None


DEST_PATH = r'c:\src\inflearn'
page_url = 'https://www.inflearn.com/'
os_name_inhibit = ['\\', '/', ':', '*', '?', '"', '<', '>', '|']


def clear_line():
    print(f'{" ":>100}', end='\r')


# 경로나 파일 명에서 쓸 수 없는 문자들을 삭제하기
def trim_path(name: str):
    for inhibit in os_name_inhibit:
        name = name.replace(inhibit, '')
    return name


def make_dest_path(dest):
    os.makedirs(dest, exist_ok=True)
    return dest


def load_env_file(path=".env"):
    env_path = os.path.abspath(path)
    loaded = set()
    if not os.path.isfile(env_path):
        return loaded
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip().lstrip("\ufeff")
            val = val.strip().strip("\"").strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
                loaded.add(key)
    return loaded


class VideoCrawler:
    def __init__(self):
        self._driver = webdriver.Chrome()
        self._wait = WebDriverWait(self._driver, 20)
        make_dest_path(DEST_PATH)

    def _safe_ascii(self, text):
        try:
            return text.encode("ascii", "backslashreplace").decode("ascii")
        except Exception:
            return text

    def _dump_debug(self, prefix="login_fail"):
        os.makedirs("debug", exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        png = f"debug/{prefix}_{ts}.png"
        html = f"debug/{prefix}_{ts}.html"

        try:
            self._driver.save_screenshot(png)
        except Exception:
            pass

        try:
            with open(html, "w", encoding="utf-8") as f:
                f.write(self._driver.page_source)
        except Exception:
            pass

        print("\n[DEBUG]")
        print("  url  :", self._driver.current_url)
        print("  title:", self._driver.title)
        print("  saved:", png, html)

    def _wait_any(self, css_list, timeout=20):
        end = time.time() + timeout
        last_err = None
        while time.time() < end:
            for css in css_list:
                try:
                    el = self._driver.find_element(By.CSS_SELECTOR, css)
                    if el.is_displayed():
                        return el
                except Exception as e:
                    last_err = e
            time.sleep(0.2)
        raise TimeoutException(f"None of selectors found: {css_list}") from last_err
    
    def _collect_m3u8_requests(self, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            reqs = [
                r for r in self._driver.requests
                if "https://vod.inflearn.com" in r.url and ".m3u8" in r.url
            ]
            if reqs:
                return reqs
            time.sleep(0.5)
        return []

    def _m3u8_duration(self, content_bytes):
        try:
            text = content_bytes.decode("utf-8", "ignore")
        except Exception:
            return 0.0
        total = 0.0
        for m in re.finditer(r"#EXTINF:([0-9\\.]+),", text):
            try:
                total += float(m.group(1))
            except Exception:
                pass
        return total

    def _prefetch_keys(self, key_paths, timeout=10):
        cached = {}
        if not key_paths:
            return cached
        end = time.time() + timeout
        pending = set(key_paths)
        while time.time() < end and pending:
            for r in self._driver.requests:
                if "/key/" not in r.url or not r.response:
                    continue
                path = urlsplit(r.url).path
                if path in pending and getattr(r.response, "status_code", None) == 200:
                    if r.response.body:
                        cached[path] = r.response.body
                        pending.discard(path)
            time.sleep(0.2)
        return cached

    def _find_key_request(self, key_path, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            for r in self._driver.requests:
                if "/key/" not in r.url or not r.response:
                    continue
                if key_path in r.url:
                    return r
            time.sleep(0.2)
        return None

    def _fetch_key_via_browser(self, url):
        try:
            self._driver.set_script_timeout(10)
            script = """
                const url = arguments[0];
                const callback = arguments[1];
                fetch(url, {credentials: 'include'})
                    .then(r => r.arrayBuffer())
                    .then(buf => {
                        const bytes = new Uint8Array(buf);
                        let binary = '';
                        for (let i = 0; i < bytes.length; i++) {
                            binary += String.fromCharCode(bytes[i]);
                        }
                        callback(btoa(binary));
                    })
                    .catch(() => callback(null));
            """
            b64 = self._driver.execute_async_script(script, url)
            if not b64:
                return None
            return base64.b64decode(b64)
        except Exception:
            return None
    def _debug_unit_diagnostics(self):
        self._dump_debug("no_units")
        try:
            count_a_unit = len(self._driver.find_elements(By.CSS_SELECTOR, "a.unit_item"))
            count_unit = len(self._driver.find_elements(By.CSS_SELECTOR, ".unit_item"))
            count_title = len(self._driver.find_elements(By.CSS_SELECTOR, ".title"))
            count_curriculum = len(self._driver.find_elements(
                By.CSS_SELECTOR, "[class*='curriculum'], [data-testid*='curriculum']"
            ))
            print("[DEBUG] selector counts:")
            print(f"  a.unit_item: {count_a_unit}")
            print(f"  .unit_item: {count_unit}")
            print(f"  .title: {count_title}")
            print(f"  curriculum_like: {count_curriculum}")
        except Exception as e:
            print("[DEBUG] selector check failed:", e)

    def login(self):
        loaded_keys = load_env_file()
        login_id = os.getenv("INFLEARN_EMAIL", "").strip()
        pw = os.getenv("INFLEARN_PASSWORD", "").strip()
        if not login_id or not pw:
            env_path = os.path.abspath(".env")
            missing = []
            if not login_id:
                missing.append("INFLEARN_EMAIL")
            if not pw:
                missing.append("INFLEARN_PASSWORD")
            raise RuntimeError(
                f"Missing {', '.join(missing)} in .env (checked {env_path}, loaded keys: {sorted(loaded_keys)})"
            )

        self._driver.get("https://www.inflearn.com/signin")

        try:
            # ✅ 이메일 input: type=email 이 아닐 수 있어서 후보를 넓게 잡음
            email_input = self._wait_any([
                'input[type="email"]',
                'input[name="email"]',
                'input[placeholder*="이메일"]',
                'input.form__input--email',
                'input.e-sign-in-input[type="text"]',   # 혹시 텍스트로 되어있는 경우
            ], timeout=20)

            pw_input = self._wait_any([
                'input[type="password"]',
                'input[name="password"]',
                'input[placeholder*="비밀번호"]',
                'input.e-sign-in-input[type="password"]',
            ], timeout=20)

            email_input.clear()
            email_input.send_keys(login_id)
            pw_input.clear()
            pw_input.send_keys(pw)

            # ✅ 로그인 버튼도 후보 셀렉터 여러 개
            submit_btn = self._wait_any([
                "button.e-sign-in",
                'button[type="submit"]',
            ], timeout=20)
            submit_btn.click()

            # 로그인 페이지를 벗어났는지 체크
            self._wait.until(lambda d: "signin" not in d.current_url)

            print("로그인되었습니다.")
            self._driver.get(page_url + "my-courses")
            lecture_url = os.getenv("INFLEARN_LECTURE_URL", "").strip()
            if lecture_url:
                self._driver.get(lecture_url)

        except TimeoutException:
            self._dump_debug("signin_timeout")
            raise

        
    def get_video_from_current_page(self):
        return self.get_video_from_url(self._driver.current_url)

    def get_videos_from_current_lecture(self):
        return self.get_all_video_from_lecture(self._driver.current_url)

    # start, end는 시작과 끝 지점의 인덱스
    def get_all_video_from_lecture(self, url, start=0, end=4321):
        if self._driver.current_url != url:
            self._driver.get(url)

        try:
            self._wait_any(["a.unit_item", "li[data-unit-id]"], timeout=20)
        except TimeoutException:
            try:
                tab = self._wait_any([
                    "button[title='커리큘럼']",
                    "button[data-dd-action-name='커리큘럼 탭변경']",
                    "button[title='Curriculum']",
                ], timeout=5)
                tab.click()
                time.sleep(1)
            except Exception:
                pass

        unit_urls = []
        try:
            unit_urls = [unit.get_attribute('href') for unit in
                         self._driver.find_elements(By.XPATH, "//a[@class='unit_item']")]
        except selenium_exceptions.NoSuchElementException:
            unit_urls = []

        # Fallback: modern lecture page uses data-unit-id without hrefs.
        if not unit_urls:
            unit_ids = [el.get_attribute("data-unit-id") for el in
                        self._driver.find_elements(By.CSS_SELECTOR, "li[data-unit-id]")]
            unit_ids = [uid for uid in unit_ids if uid]
            if unit_ids:
                base_url = self._driver.current_url
                if "unitId=" in base_url:
                    unit_urls = [base_url.replace(
                        base_url.split("unitId=")[1].split("&")[0], uid
                    ) for uid in unit_ids]
                else:
                    joiner = "&" if "?" in base_url else "?"
                    unit_urls = [f"{base_url}{joiner}unitId={uid}" for uid in unit_ids]

        if not unit_urls:
            print('No lecture units found on this page. Open a lecture page first.')
            print("  current_url:", self._driver.current_url)
            self._debug_unit_diagnostics()
            return None
        
        max_units_env = os.getenv("INFLEARN_MAX_UNITS", "").strip()
        if max_units_env.isdigit():
            max_units = max(1, int(max_units_env))
            end = min(end, start + max_units - 1)

        env_start = os.getenv("INFLEARN_START_INDEX", "").strip()
        env_end = os.getenv("INFLEARN_END_INDEX", "").strip()
        if env_start.isdigit():
            start = int(env_start)
        if env_end.isdigit():
            end = int(env_end)
        if start > end:
            raise ValueError('start value never greater than end')
        if end >= len(unit_urls):
            end = len(unit_urls) - 1
        size = end - start + 1

        env_unit_id = os.getenv("INFLEARN_UNIT_ID", "").strip()
        if env_unit_id:
            filtered = [u for u in unit_urls if f"unitId={env_unit_id}" in u]
            if not filtered:
                print("INFLEARN_UNIT_ID가 목록에 없습니다:", env_unit_id)
                return None
            unit_urls = filtered
            start = 0
            end = 0

        for idx, unit_url in enumerate(unit_urls):
            if start > idx or idx > end:
                continue
            print(f'전체 강의 다운로드 {size} 중 {idx + 1}...')
            ok = self.get_video_from_url(unit_url)
            if ok is False:
                print("중단: 현재 강의에서 실패했습니다.")
                break

        print('강좌 다운로드가 모두 완료되었습니다.')

    def get_video_from_url(self, url):
        # requests 목록 초기화
        del self._driver.requests

        if self._driver.current_url != url:
            print('connecting to url...', url)
            self._driver.get(url)

        try:
            self._wait.until(lambda d: d.find_element(By.TAG_NAME, 'video'))
        except Exception:
            print('동영상이 없는 페이지입니다.')
            return False

        print('영상 대기 중...', end='\r')
        elapsed = 0
        while True:
            vid_js = None
            try:
                vid_js = self._driver.find_element(By.CSS_SELECTOR, '.video-js')
            except Exception:
                pass
            if vid_js and 'vjs-playing' in vid_js.get_attribute('class'):
                break
            try:
                video_el = self._driver.find_element(By.TAG_NAME, 'video')
                if video_el.get_attribute("src"):
                    break
            except Exception:
                pass
            time.sleep(0.5)
            elapsed += 0.5
            if elapsed > 10:
                try:
                    self._driver.find_element(By.XPATH, "//button[contains(@class, 'vjs-paused')]").click()
                except Exception as e:
                    print(e)
            if elapsed > 30:
                print('대기 시간이 너무 오래 걸립니다...')
                return False
        print('영상 로드 완료', end='\r')
        # 만약 영상이 재생 중이라면 멈추게 하기.
        try:
            self._driver.find_element(By.XPATH, "//button[contains(@class, 'vjs-playing')]").click()
        except selenium_exceptions.NoSuchElementException:
            pass

        # 이거는 제외하고 받아오기
        title_except = ['목차', '커뮤니티 게시판', '노트']
        # ['현재 강의 제목', '전체 강의 제목', ...[목차 순서대로]]
        titles = [elem.text for elem in self._driver.find_elements(By.CLASS_NAME, 'title')
                  if elem.text not in title_except]

        lecture_title = None
        try:
            lecture_title = self._driver.find_element(By.CSS_SELECTOR, "video[data-unit-title]") \
                .get_attribute("data-unit-title")
        except Exception:
            pass
        if not lecture_title:
            try:
                lecture_title = self._driver.find_element(By.CSS_SELECTOR, ".unit-title").text
            except Exception:
                pass
        if not lecture_title and len(titles) > 1:
            lecture_title = titles[1]
        lecture_title = trim_path(lecture_title or "lecture")

        course_title = None
        course_index = 0
        if titles:
            try:
                course_title = self._driver.find_element(By.CSS_SELECTOR, ".is-current .title").text
                course_index = titles[2:].index(course_title) + 1
            except Exception:
                course_title = None
        if not course_title:
            course_title = (self._driver.title or "").replace(" | 학습 페이지", "").strip()
        course_title = trim_path(course_title or "course")

        # Try to parse numeric prefix like "42. ..."
        lead = lecture_title.split(".", 1)[0].strip()
        if lead.isdigit():
            course_index = int(lead)
        raw_filename = f'{course_index} - {course_title}.ts'
        course_filename = f'{course_index} - {course_title}.mp4'
        print(f'[{lecture_title} - {course_title}] 강좌를 다운로드합니다.')
        # 파일이 이미 존재한다면 기본적으로 새로 생성하지 않는다.
        force = os.getenv("INFLEARN_FORCE", "").strip() == "1"
        if os.path.isfile(os.path.join(DEST_PATH, lecture_title, course_filename)) or \
           os.path.isfile(os.path.join(DEST_PATH, lecture_title, raw_filename)):
            print(os.path.join(DEST_PATH, lecture_title, course_filename))
            if not force:
                print('이미 존재하는 강의입니다. 다운로드하지 않습니다.')
                return None
            try:
                os.remove(os.path.join(DEST_PATH, lecture_title, course_filename))
            except Exception:
                pass
            try:
                os.remove(os.path.join(DEST_PATH, lecture_title, raw_filename))
            except Exception:
                pass

        headers = {}
        session = requests.Session()
        root_url = None
        meta_info_url = None
        sources = None
        segments = None
        signed_query = ""
        m3u8_reqs = self._collect_m3u8_requests(timeout=15)
        if not m3u8_reqs:
            try:
                self._driver.execute_script("var v=document.querySelector('video'); if (v) v.play();")
            except Exception:
                pass
            m3u8_reqs = self._collect_m3u8_requests(timeout=15)
        preferred = None
        for r in m3u8_reqs:
            if "/encrypted/master.m3u8" in r.url:
                preferred = r
                break
        if preferred is None:
            for r in m3u8_reqs:
                if "/encrypted/" in r.url and re.search(r"/\\d+\\.m3u8", r.url):
                    preferred = r
                    break
        if preferred is None:
            for r in m3u8_reqs:
                if "/encrypted/" in r.url and \
                   "thumbnail" not in r.url and \
                   "/ko.m3u8" not in r.url and \
                   "/en.m3u8" not in r.url and \
                   "/vi.m3u8" not in r.url and \
                   "vtt.m3u8" not in r.url:
                    preferred = r
                    break
        if preferred is None and m3u8_reqs:
            preferred = m3u8_reqs[0]

        if preferred:
            request = preferred
            parsed = urlsplit(request.url)
            signed_query = f"?{parsed.query}" if parsed.query else ""
            root_url = request.url[:request.url.rfind('/')] + '/'
            headers.update(request.headers)
            headers.setdefault("Referer", self._driver.current_url)
            headers.setdefault("Origin", "https://www.inflearn.com")
            try:
                safe_url = request.url.encode("ascii", "backslashreplace").decode("ascii")
                print(f"  [M3U8] url: {safe_url}")
                print(f"  [M3U8] has_cookie: {any(k.lower() == 'cookie' for k in headers.keys())}")
            except Exception:
                pass
            try:
                if not any(k.lower() == "cookie" for k in headers.keys()):
                    cookie_header = "; ".join(
                        f"{c['name']}={c['value']}" for c in self._driver.get_cookies()
                    )
                    if cookie_header:
                        headers["Cookie"] = cookie_header
            except Exception:
                pass
            cookie_jar = {}
            try:
                cookie_jar = {c["name"]: c["value"] for c in self._driver.get_cookies()}
            except Exception:
                pass
            session.headers.update(headers)
            if cookie_jar:
                session.cookies.update(cookie_jar)
            resp = session.get(url=request.url, headers=headers)
            try:
                os.makedirs("debug", exist_ok=True)
                master_path = os.path.join("debug", f"master_{time.strftime('%Y%m%d_%H%M%S')}.m3u8")
                with open(master_path, "wb") as f:
                    f.write(resp.content)
                print("  [M3U8] saved:", master_path)
            except Exception:
                pass
            if b"skd://" in resp.content or b"METHOD=SAMPLE" in resp.content:
                print("DRM 감지: 현재 스트림은 지원하지 않습니다.")
                return False
            lines = [line for line in resp.content.splitlines() if line]
            if lines:
                # If this is already a media playlist, use it directly.
                if any(b".ts" in line for line in lines):
                    current_key_uri = None
                    current_iv = None
                    tmp_segments = []
                    print(f"  [M3U8] selected duration: {self._m3u8_duration(resp.content):.1f}s")
                    for line in lines:
                        if line.startswith(b"#EXT-X-KEY:"):
                            text = line.decode("utf-8", "ignore")
                            m = re.search(r'URI="([^"]+)"', text)
                            current_key_uri = m.group(1) if m else None
                            m = re.search(r'IV=0x([0-9a-fA-F]+)', text)
                            current_iv = bytes.fromhex(m.group(1)) if m else None
                            continue
                        if line.startswith(b"#"):
                            continue
                        if line.startswith(b"http"):
                            seg = line.decode("utf-8", "ignore")
                        else:
                            decoded = line.decode("utf-8", "ignore")
                            if decoded and decoded.isascii():
                                seg = decoded
                            else:
                                seg = quote_from_bytes(line)
                        tmp_segments.append((seg, current_key_uri, current_iv))
                    segments = tmp_segments
                else:
                    stream_lines = []
                    last_was_stream = False
                    for line in lines:
                        if line.startswith(b"#EXT-X-STREAM-INF"):
                            last_was_stream = True
                            continue
                        if line.startswith(b"#"):
                            continue
                        if last_was_stream and b".m3u8" in line:
                            if b"thumbnail" in line or b"vtt.m3u8" in line or b"ko.m3u8" in line or b"en.m3u8" in line or b"vi.m3u8" in line:
                                last_was_stream = False
                                continue
                            stream_lines.append(line)
                        last_was_stream = False
                    if stream_lines:
                        best_line = None
                        best_dur = -1.0
                        for line in stream_lines:
                            if line.startswith(b"http"):
                                candidate = line.decode("utf-8", "ignore")
                            else:
                                decoded = line.decode("utf-8", "ignore")
                                if decoded and decoded.isascii():
                                    candidate = decoded
                                else:
                                    candidate = quote_from_bytes(line)
                            cand_url = candidate if candidate.startswith("http") else (root_url + candidate)
                            if signed_query and "?" not in candidate:
                                cand_url += signed_query
                            try:
                                cand_resp = session.get(url=cand_url, headers=headers)
                                if cand_resp.status_code != 200:
                                    continue
                                dur = self._m3u8_duration(cand_resp.content)
                                if dur > best_dur:
                                    best_dur = dur
                                    best_line = candidate
                            except Exception:
                                continue
                        if best_line:
                            print(f"  [M3U8] selected duration: {best_dur:.1f}s")
                            meta_info_url = best_line
        if root_url is None:
            try:
                os.makedirs("debug", exist_ok=True)
                req_path = os.path.join("debug", f"requests_{time.strftime('%Y%m%d_%H%M%S')}.txt")
                with open(req_path, "w", encoding="utf-8") as f:
                    for r in list(self._driver.requests)[-200:]:
                        f.write(f"{r.url}\n")
                print("  saved requests:", req_path)
            except Exception:
                pass
            print('root url을 찾을 수 없습니다.')
            return False
        if segments is None and sources is None and not meta_info_url:
            print('m3u8 소스 경로를 찾을 수 없습니다.')
            return False

        if sources is None and segments is None:
            meta_url = root_url + meta_info_url
            if signed_query and "?" not in meta_info_url:
                meta_url += signed_query
            resp = session.get(url=meta_url, headers=headers)
            try:
                os.makedirs("debug", exist_ok=True)
                meta_path = os.path.join("debug", f"meta_{time.strftime('%Y%m%d_%H%M%S')}.m3u8")
                with open(meta_path, "wb") as f:
                    f.write(resp.content)
                print("  [M3U8] saved:", meta_path)
            except Exception:
                pass
            if resp.status_code != 200:
                print(resp.text)
                return False
            if b"skd://" in resp.content or b"METHOD=SAMPLE" in resp.content:
                print("DRM 감지: 현재 스트림은 지원하지 않습니다.")
                return False
            # get source url list
            current_key_uri = None
            current_iv = None
            tmp_segments = []
            for line in resp.content.splitlines():
                if not line:
                    continue
                if line.startswith(b"#EXT-X-KEY:"):
                    text = line.decode("utf-8", "ignore")
                    m = re.search(r'URI="([^"]+)"', text)
                    current_key_uri = m.group(1) if m else None
                    m = re.search(r'IV=0x([0-9a-fA-F]+)', text)
                    current_iv = bytes.fromhex(m.group(1)) if m else None
                    continue
                if line.startswith(b"#"):
                    continue
                if line.startswith(b"http"):
                    seg = line.decode("utf-8", "ignore")
                else:
                    decoded = line.decode("utf-8", "ignore")
                    if decoded and decoded.isascii():
                        seg = decoded
                    else:
                        seg = quote_from_bytes(line)
                tmp_segments.append((seg, current_key_uri, current_iv))
            segments = tmp_segments
        max_segments_env = os.getenv("INFLEARN_MAX_SEGMENTS", "").strip()
        if max_segments_env.isdigit():
            max_segments = max(1, int(max_segments_env))
            if segments is not None:
                segments = segments[:max_segments]
            elif sources is not None:
                sources = sources[:max_segments]
        videos = []
        fail_shown = 0
        key_cache = {}
        key_token_cache = {}
        if segments is not None:
            items = segments
        else:
            items = [(s, None, None) for s in (sources or [])]
        key_paths = []
        for _, key_uri, _ in items:
            if not key_uri:
                continue
            path = urlsplit(key_uri).path
            if path and path not in key_paths:
                key_paths.append(path)
        try:
            self._driver.execute_script("var v=document.querySelector('video'); if (v) { v.muted=true; v.play(); }")
            time.sleep(2)
        except Exception:
            pass
        try:
            self._driver.execute_script(
                "var v=document.querySelector('video'); if (v) { v.currentTime=0; v.playbackRate=4.0; v.muted=true; v.play(); }"
            )
        except Exception:
            pass
        key_cache.update(self._prefetch_keys(key_paths, timeout=10))
        last_key_log = None
        for idx, (src, key_uri, iv) in enumerate(items):
            print(f'영상 다운로드 중... ({idx / len(items) * 100:<4.1f}%)', end='\r')
            if src.startswith("http"):
                seg_url = src
            else:
                seg_url = root_url + src
            if signed_query and "?" not in src:
                seg_url += signed_query
            resp = session.get(url=seg_url, headers=headers)
            if resp.status_code == 200:
                content = resp.content
                if key_uri:
                    if AES is None:
                        print("AES 라이브러리가 없어 복호화를 진행할 수 없습니다. (pycryptodome 설치 필요)")
                        return False
                    key_url = key_uri if key_uri.startswith("http") else (root_url + key_uri)
                    key_headers = headers
                    key_req = None
                    key = None
                    try:
                        key_path = urlsplit(key_url).path
                        key_base = "/".join(key_path.split("/")[:3]) if key_path else ""
                        if key_base:
                            token = key_token_cache.get(key_base)
                            if not token:
                                for r in reversed(self._driver.requests):
                                    if key_base in r.url and "key=" in r.url and getattr(r.response, "status_code", None) == 200:
                                        m = re.search(r"[?&]key=([^&]+)", r.url)
                                        if m:
                                            token = m.group(1)
                                            key_token_cache[key_base] = token
                                            break
                            if token and "key=" not in key_url:
                                joiner = "&" if "?" in key_url else "?"
                                key_url += f"{joiner}key={token}"
                        if key_path and key_path != last_key_log:
                            print(f"\n  [KEY] path: {self._safe_ascii(key_path)}")
                            last_key_log = key_path
                        if key_path in key_cache:
                            key = key_cache.get(key_path)
                        else:
                            key_req = self._find_key_request(key_path, timeout=15)
                            if key_req:
                                key_url = key_req.url
                                key_headers = {**headers, **key_req.headers}
                                if key_req.response and getattr(key_req.response, "body", None):
                                    key = key_req.response.body
                    except Exception:
                        pass
                    key_url_raw = key_url
                    key_url_signed = None
                    if signed_query and "key=" not in key_url and "Key-Pair-Id=" not in key_url and "Policy=" not in key_url:
                        joiner = "&" if "?" in key_url else "?"
                        key_url_signed = key_url + joiner + signed_query.lstrip("?")
                    key = key_cache.get(key_url_raw) or key_cache.get(urlsplit(key_url_raw).path)
                    if key is None:
                        if key_req and key_req.response and getattr(key_req.response, "body", None):
                            key = key_req.response.body
                        if key is None:
                            tried = []
                            for candidate in (key_req.url if key_req else None, key_url_raw, key_url_signed):
                                if not candidate or candidate in tried:
                                    continue
                                tried.append(candidate)
                                key_resp = session.get(url=candidate, headers=key_headers)
                                if key_resp.status_code == 200 and key_resp.content:
                                    key = key_resp.content
                                    key_url = candidate
                                    break
                                browser_key = self._fetch_key_via_browser(candidate)
                                if browser_key:
                                    key = browser_key
                                    key_url = candidate
                                    break
                            if key is None:
                                last_url = tried[-1] if tried else key_url_raw
                                safe_key_url = self._safe_ascii(last_url)
                                resp_preview = ""
                                try:
                                    resp_preview = (key_resp.text or "")[:200]
                                except Exception:
                                    resp_preview = ""
                                print(f"[KEY FAIL] status={getattr(key_resp, 'status_code', 'NA')} url={safe_key_url}")
                                if resp_preview:
                                    print(f"[KEY FAIL] body={self._safe_ascii(resp_preview)}")
                                print(f"[KEY FAIL] segment={idx} seg_url={self._safe_ascii(seg_url)}")
                                try:
                                    os.makedirs("debug", exist_ok=True)
                                    ts = time.strftime("%Y%m%d_%H%M%S")
                                    dbg_path = os.path.join("debug", f"key_fail_{ts}.txt")
                                    with open(dbg_path, "w", encoding="utf-8") as f:
                                        f.write(f"key_url={key_url_raw}\n")
                                        if key_url_signed:
                                            f.write(f"key_url_signed={key_url_signed}\n")
                                        f.write(f"segment={idx}\n")
                                        f.write(f"seg_url={seg_url}\n")
                                        f.write("cookies:\n")
                                        try:
                                            for c in self._driver.get_cookies():
                                                f.write(f"  {c.get('name')}={c.get('value')}\n")
                                        except Exception:
                                            pass
                                        f.write("recent key requests:\n")
                                        for r in list(self._driver.requests)[-200:]:
                                            if "/key/" in r.url:
                                                f.write(f"  {r.url} status={getattr(r.response, 'status_code', None)}\n")
                                    print(f"[KEY FAIL] saved debug: {dbg_path}")
                                except Exception:
                                    pass
                                return False
                        key_cache[key_url] = key
                        key_cache[urlsplit(key_url).path] = key
                    if key is None:
                        print(f"[KEY FAIL] empty key: {self._safe_ascii(key_url)}")
                        print(f"[KEY FAIL] segment={idx} seg_url={self._safe_ascii(seg_url)}")
                        return False
                    if len(key) != 16:
                        print(f"[KEY FAIL] invalid key length: {len(key)}")
                        print(f"[KEY FAIL] url={self._safe_ascii(key_url)}")
                        print(f"[KEY FAIL] segment={idx} seg_url={self._safe_ascii(seg_url)}")
                        return False
                    if iv is None:
                        iv = idx.to_bytes(16, "big")
                    if len(iv) != 16:
                        print("[KEY FAIL] invalid IV length")
                        print(f"[KEY FAIL] segment={idx} seg_url={self._safe_ascii(seg_url)}")
                        return False
                    try:
                        content = AES.new(key, AES.MODE_CBC, iv).decrypt(content)
                    except Exception as e:
                        print("[DECRYPT FAIL]", e)
                        print(f"[DECRYPT FAIL] url={self._safe_ascii(key_url)}")
                        print(f"[DECRYPT FAIL] segment={idx} seg_url={self._safe_ascii(seg_url)}")
                        return False
                videos.append(content)
            elif fail_shown < 3:
                fail_shown += 1
                preview = resp.text[:200] if resp.text else ""
                safe_url = seg_url.encode("ascii", "backslashreplace").decode("ascii")
                print(f"\n  [SEGMENT FAIL] {resp.status_code} {safe_url}")
                if preview:
                    safe_preview = preview.encode("ascii", "backslashreplace").decode("ascii")
                    print(f"  [SEGMENT BODY] {safe_preview}")
        total_bytes = sum(len(v) for v in videos)
        print('영상 다운로드 완료. 파일로 다운로드합니다.')
        print(f'  segments: {len(videos)}, bytes: {total_bytes}')

        # 다운로드 받을 장소.
        src_path = os.path.join(DEST_PATH, lecture_title)
        if not os.path.isdir(src_path):
            os.mkdir(src_path)
        raw_path = os.path.join(src_path, raw_filename)
        with open(raw_path, 'wb') as f:
            for idx, vid in enumerate(videos):
                print(f'??? ???????.. ({idx / len(videos) * 100:<4.1f}%)', end='\r')
                f.write(vid)
            print('?????? ???.', lecture_title, '-', course_title)
            videos.clear()
        remux = os.getenv("INFLEARN_REMUX", "").strip() == "1"
        if remux:
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                print("ffmpeg? ?? mp4? ??? ? ????. (INFLEARN_REMUX=1)")
                print("  saved:", raw_path)
                return True
            out_path = os.path.join(src_path, course_filename)
            cmd = [ffmpeg, "-y", "-i", raw_path, "-c", "copy", out_path]
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                os.remove(raw_path)
                print("mp4 ?? ??:", out_path)
            except Exception as e:
                print("mp4 ?? ??:", e)
        return True

if __name__ == '__main__':
    vc = VideoCrawler()
    vc.login()
    vc.get_videos_from_current_lecture()
