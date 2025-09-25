import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import requests
from bs4 import BeautifulSoup
import csv
import os
import datetime
import time
import threading
from plyer import notification
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates
from matplotlib import font_manager, rc
import sys
import schedule
import winreg # For Windows registry access
import getpass # For getting the current user on macOS
import plistlib # For macOS startup file
import re # 정규표현식 라이브러리 추가

# ====================================================================
# 프로그램 버전 정의
# ====================================================================
__version__ = "1.0.0"


# 폰트 설정 (운영체제에 따라 자동 선택)
if sys.platform == 'darwin': # macOS
    rc('font', family='AppleGothic')
    rc('axes', unicode_minus=False)
elif sys.platform == 'win32':  # Windows
    try:
        font_name = font_manager.FontProperties(fname="c:/Windows/Fonts/malgun.ttf").get_name()
        rc('font', family=font_name)
    except:
        pass # Malgun Gothic 폰트가 없는 경우

# ====================================================================
# A. 핵심 로직: 데이터 수집 및 분석
# ====================================================================

def log_message(level, message):
    """지정된 형식으로 콘솔에 로그 메시지를 출력합니다."""
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] [{level}] {message}")

def get_stock_price(stock_code):
    """지정된 주식 코드의 현재 가격을 크롤링하고 회사명을 반환합니다."""
    url = f"https://finance.naver.com/item/main.naver?code={stock_code}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            price_element = soup.select_one('.today .blind')
            name_element = soup.select_one('.wrap_company h2 a')
            current_price = int(price_element.text.replace(',', '')) if price_element else None
            company_name = name_element.text if name_element else "Unknown"
            return current_price, company_name
    except Exception as e:
        log_message("ERROR", f"가격 크롤링 실패: {e}")
    return None, "Unknown"

def get_historical_data_from_naver(stock_code, pages=10):
    """
    네이버 금융에서 과거 일별 데이터를 크롤링합니다. (종가 기준)
    """
    log_message("INFO", f"과거 데이터 크롤링 시작: {stock_code}")
    data = []
    url_base = f"https://finance.naver.com/item/sise_day.naver?code={stock_code}"
    headers = {'User-Agent': 'Mozilla/5.0'}

    for page in range(1, pages + 1):
        url = f"{url_base}&page={page}"
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                rows = soup.find('table', class_='type2').find_all('tr')
                
                for row in rows[2:]: # 헤더와 불필요한 행 제외
                    cols = row.find_all('td')
                    if len(cols) > 1:
                        date_str = cols[0].text.strip()
                        # 종가(Closing Price)
                        price_str = cols[1].text.strip().replace(',', '')
                        
                        try:
                            price = int(price_str)
                            # 일별 데이터이므로, 시간은 00:00으로 통일
                            timestamp = datetime.datetime.strptime(date_str, '%Y.%m.%d').strftime('%Y-%m-%d 00:00')
                            data.append({'timestamp': timestamp, 'price': price})
                        except (ValueError, IndexError):
                            continue
            else:
                log_message("WARNING", f"과거 데이터 크롤링 중 오류: HTTP {response.status_code}")
                break
        except Exception as e:
            log_message("ERROR", f"과거 데이터 크롤링 실패: {e}")
            break
            
    # 날짜 기준 오름차순으로 정렬
    data.sort(key=lambda x: datetime.datetime.strptime(x['timestamp'], '%Y-%m-%d %H:%M'))
    log_message("SUCCESS", f"과거 데이터 크롤링 완료: 총 {len(data)}개 데이터 수집")
    return data

def save_data(file_path, data):
    """
    주식 데이터를 CSV 파일에 저장합니다.
    """
    headers = ['Timestamp', 'Price']
    
    # 디렉토리가 없으면 생성
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    
    with open(file_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(data)
    log_message("INFO", f"데이터 저장 완료: '{file_path}'")

def get_historical_prices_from_csv(file_path):
    """CSV 파일에서 시간별 데이터를 불러옵니다."""
    data = []
    if os.path.exists(file_path) and os.stat(file_path).st_size > 0:
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            try:
                # 헤더 건너뛰기
                next(reader)
                for row in reader:
                    try:
                        timestamp_str = row[0]
                        price = int(row[1])
                        data.append({'timestamp': datetime.datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M'), 'price': price})
                    except (ValueError, IndexError):
                        continue
            except StopIteration:
                pass
    return data

def send_notification(title, message):
    """데스크톱 알림을 보냅니다."""
    notification.notify(title=title, message=message, app_name='Stock Notifier', timeout=10)
    log_message("INFO", f"알림 발송: {title}")
    
# ====================================================================
# 운영체제별 자동 실행 설정 로직
# ====================================================================

def add_to_startup_windows(app_name, file_path):
    try:
        key = winreg.HKEY_CURRENT_USER
        key_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Run"
        reg_key = winreg.OpenKey(key, key_path, 0, winreg.KEY_SET_VALUE)
        command = f'"{sys.executable}" "{file_path}"'
        winreg.SetValueEx(reg_key, app_name, 0, winreg.REG_SZ, command)
        winreg.CloseKey(reg_key)
        return True
    except Exception as e:
        log_message("ERROR", f"윈도우 시작 프로그램 등록 실패: {e}")
        return False

def remove_from_startup_windows(app_name):
    try:
        key = winreg.HKEY_CURRENT_USER
        key_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Run"
        reg_key = winreg.OpenKey(key, key_path, 0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(reg_key, app_name)
        winreg.CloseKey(reg_key)
        return True
    except FileNotFoundError:
        return True # 이미 없으면 성공
    except Exception as e:
        log_message("ERROR", f"윈도우 시작 프로그램 제거 실패: {e}")
        return False

def add_to_startup_macos(app_name, file_path):
    try:
        user_name = getpass.getuser()
        plist_dir = os.path.expanduser(f'/Users/{user_name}/Library/LaunchAgents/')
        
        if not os.path.exists(plist_dir):
            os.makedirs(plist_dir)
            
        plist_path = os.path.join(plist_dir, f'{app_name}.plist')
        
        plist_content = {
            'Label': app_name,
            'ProgramArguments': [
                sys.executable,
                file_path
            ],
            'RunAtLoad': True
        }
        
        with open(plist_path, 'wb') as f:
            plistlib.dump(plist_content, f)
            
        return True
    except Exception as e:
        log_message("ERROR", f"macOS 로그인 항목 등록 실패: {e}")
        return False

def remove_from_startup_macos(app_name):
    try:
        user_name = getpass.getuser()
        plist_dir = os.path.expanduser(f'/Users/{user_name}/Library/LaunchAgents/')
        plist_path = os.path.join(plist_dir, f'{app_name}.plist')
        
        if os.path.exists(plist_path):
            os.remove(plist_path)
        return True
    except Exception as e:
        log_message("ERROR", f"macOS 로그인 항목 제거 실패: {e}")
        return False

# ====================================================================
# B. GUI 애플리케이션 클래스
# ====================================================================

class StockApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("주식 가격 분석 프로그램")
        self.geometry("1000x700")
        
        # GUI 변수들
        self.stock_code = tk.StringVar(value='005930')
        self.notification_times = tk.StringVar(value='09:00,10:00,11:00,12:00,13:00,14:00,15:00,15:30')
        self.periods = tk.StringVar(value='20,120,250')
        # 기본 파일 경로를 Documents 폴더로 설정
        default_file_path = os.path.join(os.path.expanduser('~'), 'Documents', 'stock_data.csv')
        self.file_path = tk.StringVar(value=default_file_path)
        self.startup_var = tk.BooleanVar()
        
        # 이전 설정값을 저장할 변수
        self.prev_stock_code = self.stock_code.get()
        self.prev_notification_times = self.notification_times.get()
        self.prev_periods = self.periods.get()
        self.prev_file_path = self.file_path.get()
        self.prev_startup_status = self.startup_var.get()
        
        # 프로그램 시작 시 자동 실행 상태 확인 및 GUI에 반영
        self.check_startup_status()
        self.company_name = "Unknown"
        self.alert_conditions = []
        self.alert_frame = None
        
        self.notebook = None
        self.plot_frame = None
        self.today_info_widgets = {}
        self.last_update_label = None
        
        self.scheduled_jobs = []
        
        self.load_historical_data()
        self.create_widgets()
        self.schedule_updates()
        self.load_and_display_data()
    
    def check_startup_status(self):
        """현재 운영체제에 자동 실행 설정이 되어있는지 확인합니다."""
        if sys.platform == 'win32':
            app_name = "StockPriceApp"
            try:
                key = winreg.HKEY_CURRENT_USER
                key_path = "Software\\Microsoft\\Windows\\CurrentVersion\\Run"
                reg_key = winreg.OpenKey(key, key_path, 0, winreg.KEY_READ)
                winreg.QueryValueEx(reg_key, app_name)
                self.startup_var.set(True)
            except FileNotFoundError:
                self.startup_var.set(False)
            except Exception as e:
                log_message("WARNING", f"시작 프로그램 상태 확인 실패: {e}")
                self.startup_var.set(False)
        elif sys.platform == 'darwin':
            app_name = "com.stockpriceapp.launch"
            user_name = getpass.getuser()
            plist_dir = os.path.expanduser(f'/Users/{user_name}/Library/LaunchAgents/')
            plist_path = os.path.join(plist_dir, f'{app_name}.plist')
            self.startup_var.set(os.path.exists(plist_path))

    def load_historical_data(self):
        """
        프로그램 시작 시, CSV 파일이 없거나 비어 있으면
        과거 데이터를 미리 저장합니다.
        """
        # CSV 파일이 존재하고, 비어 있지 않은지 확인
        if os.path.exists(self.file_path.get()) and os.stat(self.file_path.get()).st_size > 0:
            log_message("INFO", "기존 데이터 파일 발견. 과거 데이터 로딩을 건너뜁니다.")
            return

        log_message("INFO", "기존 데이터 파일이 없어 과거 종가 데이터를 로드합니다.")
        try:
            periods_list = [int(p) for p in self.periods.get().split(',') if p.strip().isdigit()]
            max_period = max(periods_list) if periods_list else 20
            
            # 1페이지당 약 10일치 데이터이므로, 최댓값에 따라 페이지 수 계산
            pages = (max_period // 10) + 2
            
            initial_data = get_historical_data_from_naver(self.stock_code.get(), pages=pages)
            
            if initial_data:
                data_to_save = [[d['timestamp'], d['price']] for d in initial_data]
                save_data(self.file_path.get(), data_to_save)
                log_message("SUCCESS", f"과거 데이터 로딩 완료: 총 {len(initial_data)}개의 데이터가 '{self.file_path.get()}'에 저장되었습니다.")
            else:
                log_message("ERROR", "과거 데이터 로딩 실패: 과거 데이터를 가져올 수 없습니다.")
        except Exception as e:
            log_message("ERROR", f"과거 데이터 로딩 중 오류 발생: {e}")

    def create_widgets(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(expand=True, fill='both', padx=10, pady=10)
        
        settings_frame = ttk.Frame(self.notebook)
        self.notebook.add(settings_frame, text="설정")
        self.setup_settings_tab(settings_frame)
        
        self.plot_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.plot_frame, text="시각화")
        self.setup_plot_tab(self.plot_frame)

        version_label = ttk.Label(self, text=f"v{__version__}", font=("Helvetica", 8))
        version_label.pack(side=tk.BOTTOM, anchor=tk.E, padx=5, pady=2)

    def setup_settings_tab(self, parent_frame):
        # 상단 기본 설정 프레임
        input_frame = ttk.LabelFrame(parent_frame, text="기본 설정", padding=10)
        input_frame.pack(fill='x', padx=10, pady=5)
        
        ttk.Label(input_frame, text="주식 코드 (6자리):").grid(row=0, column=0, sticky='w', padx=5, pady=5)
        ttk.Entry(input_frame, textvariable=self.stock_code).grid(row=0, column=1, sticky='ew', padx=5, pady=5)

        ttk.Label(input_frame, text="알림 시간 (형식:HH24:MM, 쉼표로 구분):").grid(row=1, column=0, sticky='w', padx=5, pady=5)
        ttk.Entry(input_frame, textvariable=self.notification_times).grid(row=1, column=1, sticky='ew', padx=5, pady=5)
        
        ttk.Label(input_frame, text="분석 기간 (일 단위, 쉼표로 구분):").grid(row=2, column=0, sticky='w', padx=5, pady=5)
        periods_entry = ttk.Entry(input_frame, textvariable=self.periods)
        periods_entry.grid(row=2, column=1, sticky='ew', padx=5, pady=5)

        ttk.Label(input_frame, text="CSV 파일 경로:").grid(row=3, column=0, sticky='w', padx=5, pady=5)
        file_path_entry = ttk.Entry(input_frame, textvariable=self.file_path, state='readonly')
        file_path_entry.grid(row=3, column=1, sticky='ew', padx=5, pady=5)
        ttk.Button(input_frame, text="...", command=self.browse_file_path).grid(row=3, column=2, padx=5, pady=5)
        
        # 자동 실행 체크박스 추가
        startup_checkbox = ttk.Checkbutton(input_frame, text="컴퓨터 시작 시 자동 실행", variable=self.startup_var)
        startup_checkbox.grid(row=4, column=0, columnspan=2, sticky='w', padx=5, pady=5)
        
        input_frame.grid_columnconfigure(1, weight=1)
        
        # 알림 조건 프레임 (동적으로 추가될 컨테이너)
        self.alert_frame = ttk.LabelFrame(parent_frame, text="알림 조건", padding=10)
        self.alert_frame.pack(fill='x', padx=10, pady=10)

        # 알림 조건 추가/제거 버튼
        alert_button_frame = ttk.Frame(self.alert_frame)
        alert_button_frame.pack(fill='x', padx=5, pady=5)
        ttk.Button(alert_button_frame, text="+ 조건 추가", command=self.add_alert_condition).pack(side='left', padx=5)
        ttk.Button(alert_button_frame, text="- 조건 제거", command=self.remove_alert_condition).pack(side='right', padx=5)
        
        self.add_alert_condition()
        
        self.periods.trace_add('write', self.update_period_combos)
        
        control_frame = ttk.Frame(parent_frame, padding=10)
        control_frame.pack(fill='x', padx=10, pady=5)
        
        self.status_label = ttk.Label(control_frame, text="상태: 준비 완료", font=("Helvetica", 12))
        self.status_label.pack(side='left', padx=10)

        # 설정 버튼
        self.update_button = ttk.Button(control_frame, text="설정", command=self.update_settings)
        self.update_button.pack(side='right')

    def validate_settings(self):
        """설정값 유효성 검사"""
        # 1. 주식 코드 검사 (6자리 숫자로만 구성)
        stock_code = self.stock_code.get().strip()
        if not re.match(r'^\d{6}$', stock_code):
            messagebox.showerror("입력 오류", "주식 코드는 6자리 숫자로만 구성되어야 합니다.")
            self.stock_code.set(self.prev_stock_code)
            return False

        # 2. 알림 시간 검사 (HH:MM 형식)
        notification_times = self.notification_times.get().strip()
        if not notification_times:
            messagebox.showerror("입력 오류", "알림 시간은 반드시 작성해야 합니다.")
            self.notification_times.set(self.prev_notification_times)
            return False
        
        time_list = [t.strip() for t in notification_times.split(',')]
        for t in time_list:
            try:
                datetime.datetime.strptime(t, '%H:%M')
            except ValueError:
                messagebox.showerror("입력 오류", f"알림 시간 '{t}'은(는) 유효한 'HH:MM' 형식이 아닙니다.")
                self.notification_times.set(self.prev_notification_times)
                return False

        # 3. 분석 기간 검사 (양의 정수)
        periods_str = self.periods.get().strip()
        if not periods_str:
            messagebox.showerror("입력 오류", "분석 기간은 반드시 작성해야 합니다.")
            self.periods.set(self.prev_periods)
            return False
            
        periods_list = [p.strip() for p in periods_str.split(',')]
        for p in periods_list:
            if not p.isdigit() or int(p) <= 0:
                messagebox.showerror("입력 오류", f"분석 기간 '{p}'은(는) 유효한 양의 정수가 아닙니다.")
                self.periods.set(self.prev_periods)
                return False
        
        # 4. CSV 파일 경로 검사
        file_path = self.file_path.get().strip()
        if not file_path:
            messagebox.showerror("입력 오류", "CSV 파일 경로는 반드시 지정해야 합니다.")
            self.file_path.set(self.prev_file_path)
            return False
        
        parent_dir = os.path.dirname(file_path)
        if parent_dir and not os.path.exists(parent_dir):
            messagebox.showerror("입력 오류", f"지정된 경로의 상위 디렉터리가 존재하지 않습니다:\n{parent_dir}")
            self.file_path.set(self.prev_file_path)
            return False

        # 5. 알림 조건 검사
        for condition in self.alert_conditions:
            try:
                period = int(condition['period'].get())
                max_pct = float(condition['max_pct'].get())
                min_pct = float(condition['min_pct'].get())
                if period <= 0 or max_pct < 0 or min_pct < 0:
                     messagebox.showerror("입력 오류", "알림 조건의 '기간'과 '비율'은 양수여야 합니다.")
                     return False
            except (ValueError, tk.TclError):
                messagebox.showerror("입력 오류", "알림 조건의 '기간'과 '비율'은 유효한 숫자로 작성해야 합니다.")
                return False

        return True

    def update_settings(self):
        # 1. 유효성 검사
        if not self.validate_settings():
            return
        
        # 2. 어떤 설정이 변경되었는지 정확하게 식별
        is_stock_code_changed = self.stock_code.get() != self.prev_stock_code
        is_time_changed = self.notification_times.get() != self.prev_notification_times
        is_periods_changed = self.periods.get() != self.prev_periods
        is_file_path_changed = self.file_path.get() != self.prev_file_path
        is_startup_changed = self.startup_var.get() != self.prev_startup_status

        # 데이터 업데이트가 필요한 변경사항이 있는지 확인
        is_data_update_needed = is_stock_code_changed or is_time_changed or is_periods_changed or is_file_path_changed
        is_any_changed = is_data_update_needed or is_startup_changed
        
        if not is_any_changed:
            messagebox.showinfo("설정", "변경된 설정이 없습니다.")
            return
        
        # 3. 변경 사항에 따라 다른 알림 및 로직 수행
        # 수정된 부분: if/elif 구조를 두 개의 독립적인 if로 변경
        if is_data_update_needed:
            changed_items = []
            if is_stock_code_changed: changed_items.append("주식 코드")
            if is_time_changed: changed_items.append("알림 시간")
            if is_periods_changed: changed_items.append("분석 기간")
            if is_file_path_changed: changed_items.append("CSV 파일 경로")
            
            changed_items_str = ", ".join(changed_items)
            
            response = messagebox.askyesno(
                "설정 변경 확인",
                f"{changed_items_str}(이)가 변경되었습니다.\n"
                "기존 데이터 파일을 업데이트하고\n모든 설정을 적용하시겠습니까?\n(CSV 파일 경로를 변경하면\n기존 데이터를 유지할 수 있습니다.)"
            )
            if response:
                self._apply_settings()
            else:
                log_message("INFO", "설정 변경이 취소되었습니다. 이전 설정으로 되돌립니다.")
                self.revert_settings()
        
        if is_startup_changed: # 수정된 부분: 독립적인 if 블록으로 변경
            response = messagebox.askyesno(
                "설정 변경 확인",
                "컴퓨터 시작 시 자동 실행 설정이 변경되었습니다.\n"
                "지금 적용하시겠습니까?"
            )
            if response:
                self._apply_startup_settings()
            else:
                log_message("INFO", "자동 실행 설정 변경이 취소되었습니다. 이전 설정으로 되돌립니다.")
                self.revert_settings()

    def revert_settings(self):
        """설정값을 이전 상태로 되돌립니다."""
        self.stock_code.set(self.prev_stock_code)
        self.notification_times.set(self.prev_notification_times)
        self.periods.set(self.prev_periods)
        self.file_path.set(self.prev_file_path)
        self.startup_var.set(self.prev_startup_status)
        self.update_period_combos()

    def _apply_startup_settings(self):
        """자동 실행 설정만 적용합니다."""
        log_message("INFO", "자동 실행 설정 변경을 반영합니다.")
        
        self.prev_startup_status = self.startup_var.get()
        
        # 자동 실행 설정/해제
        if sys.platform == 'win32':
            app_name = "StockPriceApp"
            if self.startup_var.get():
                if add_to_startup_windows(app_name, os.path.abspath(sys.argv[0])):
                    log_message("SUCCESS", "윈도우 시작 프로그램에 등록되었습니다.")
                    messagebox.showinfo("설정 적용", "컴퓨터 시작 시 자동 실행 설정이 적용되었습니다.")
                else:
                    messagebox.showerror("오류", "시작 프로그램 등록에 실패했습니다.")
            else:
                if remove_from_startup_windows(app_name):
                    log_message("SUCCESS", "윈도우 시작 프로그램에서 제거되었습니다.")
                    messagebox.showinfo("설정 적용", "컴퓨터 시작 시 자동 실행 설정이 해제되었습니다.")
                else:
                    messagebox.showerror("오류", "시작 프로그램 제거에 실패했습니다.")
        elif sys.platform == 'darwin':
            app_name = "com.stockpriceapp.launch"
            if self.startup_var.get():
                if add_to_startup_macos(app_name, os.path.abspath(sys.argv[0])):
                    log_message("SUCCESS", "macOS 로그인 항목에 등록되었습니다.")
                    messagebox.showinfo("설정 적용", "컴퓨터 시작 시 자동 실행 설정이 적용되었습니다.")
                else:
                    messagebox.showerror("오류", "시작 프로그램 등록에 실패했습니다.")
            else:
                if remove_from_startup_macos(app_name):
                    log_message("SUCCESS", "macOS 로그인 항목에서 제거되었습니다.")
                    messagebox.showinfo("설정 적용", "컴퓨터 시작 시 자동 실행 설정이 해제되었습니다.")
                else:
                    messagebox.showerror("오류", "macOS 로그인 항목 제거에 실패했습니다.")
        
    def _apply_settings(self):
        log_message("INFO", "모든 설정 변경을 반영합니다.")
        
        # 현재 설정값을 이전 설정값으로 저장
        self.prev_stock_code = self.stock_code.get()
        self.prev_notification_times = self.notification_times.get()
        self.prev_periods = self.periods.get()
        self.prev_file_path = self.file_path.get()
        self.prev_startup_status = self.startup_var.get()
        
        # 주식 코드나 파일 경로가 변경되면 과거 데이터 다시 로드
        self.load_historical_data()
        
        self.schedule_updates()
        self.setup_plot_tab(self.plot_frame) # 시각화 탭 UI 업데이트
        self.load_and_display_data()
        
        # _apply_startup_settings 로직을 이 함수 안에 포함
        # self._apply_startup_settings()


    def schedule_updates(self):
        log_message("INFO", "기존 알림 스케줄을 제거합니다.")
        for job in self.scheduled_jobs:
            schedule.cancel_job(job)
        self.scheduled_jobs = []

        log_message("INFO", "새로운 알림 시간을 예약합니다.")
        times_str = self.notification_times.get()
        times_list = [t.strip() for t in times_str.split(',') if t.strip()]

        for t in times_list:
            try:
                datetime.datetime.strptime(t, '%H:%M')
                job = schedule.every().day.at(t).do(self.start_threaded_update)
                self.scheduled_jobs.append(job)
                log_message("SUCCESS", f"알림 시간이 {t}에 예약되었습니다.")
            except ValueError:
                pass
        
        if not self.scheduled_jobs:
            log_message("WARNING", "유효한 알림 시간이 없어 자동 업데이트가 비활성화되었습니다.")
            
        if not hasattr(self, 'scheduler_thread') or not self.scheduler_thread.is_alive():
            log_message("INFO", "스케줄러 스레드를 시작합니다.")
            self.scheduler_thread = threading.Thread(target=self.run_scheduler, daemon=True)
            self.scheduler_thread.start()

    def run_scheduler(self):
        while True:
            schedule.run_pending()
            time.sleep(1)

    def start_threaded_update(self):
        log_message("INFO", "자동 업데이트 스레드 시작")
        threading.Thread(target=self.perform_update_and_notify, daemon=True).start()

    def perform_update_and_notify(self):
        log_message("INFO", "주가 데이터 업데이트를 수행합니다.")
        try:
            stock_code = self.stock_code.get()
            file_path = self.file_path.get()
            current_price, self.company_name = get_stock_price(stock_code)
            
            if current_price:
                data = get_historical_prices_from_csv(file_path)
                
                timestamp_now = datetime.datetime.now()
                # 시간 정보도 함께 반영하여 저장
                timestamp_str_now = timestamp_now.strftime('%Y-%m-%d %H:%M')
                
                # 기존 데이터의 마지막 날짜가 오늘 날짜와 같으면 덮어쓰고, 아니면 추가
                if data and data[-1]['timestamp'].date() == timestamp_now.date():
                    data[-1] = {'timestamp': timestamp_now, 'price': current_price}
                else:
                    data.append({'timestamp': timestamp_now, 'price': current_price})

                # 수정된 시간 포맷으로 데이터 저장
                data_to_save = [[d['timestamp'].strftime('%Y-%m-%d %H:%M'), d['price']] for d in data]
                save_data(file_path, data_to_save)
                
                self.after(0, self.load_and_display_data)

                alert_messages = []
                for condition in self.alert_conditions:
                    try:
                        noti_period = int(condition['period'].get())
                        noti_max_pct = float(condition['max_pct'].get())
                        noti_min_pct = float(condition['min_pct'].get())
                    except (ValueError, tk.TclError):
                        continue
                    
                    if len(data) >= noti_period:
                        recent_data = data[-noti_period:]
                        recent_prices = [d['price'] for d in recent_data]
                        
                        max_price = max(recent_prices)
                        min_price = min(recent_prices)
                        
                        pct_of_max_val = (1 - current_price / max_price) * 100 if max_price != 0 else 0
                        pct_of_min_val = (current_price / min_price - 1) * 100 if min_price != 0 else 0
                        
                        if pct_of_max_val <= noti_max_pct:
                            alert_messages.append(f"▼ {noti_period}일 최고가 근접: 현재가 {current_price}원\n(최고가 {max_price}원 대비 {pct_of_max_val:.2f}% 하락)")
                        if pct_of_min_val <= noti_min_pct:
                            alert_messages.append(f"▲ {noti_period}일 최저가 근접: 현재가 {current_price}원\n(최저가 {min_price}원 대비 {pct_of_min_val:.2f}% 상승)")

                if alert_messages:
                    title = f"주식 가격 알림 - {self.company_name} ({stock_code})"
                    message = "\n\n".join(alert_messages)
                    send_notification(title, message)
                
                log_message("SUCCESS", "주가 업데이트 완료.")
            else:
                log_message("ERROR", "주가 업데이트 실패: 가격 정보를 가져올 수 없습니다.")
                self.after(0, lambda: messagebox.showerror("업데이트 실패", "주가 정보를 가져올 수 없습니다."))
                
        except Exception as e:
            log_message("ERROR", f"주가 업데이트 중 오류 발생: {e}")
            self.after(0, lambda: messagebox.showerror("업데이트 오류", f"업데이트 중 오류가 발생했습니다: {e}"))

    def load_and_display_data(self):
        log_message("INFO", "데이터 로드 및 GUI 업데이트 시작")
        file_path = self.file_path.get()
        data = get_historical_prices_from_csv(file_path)
        
        self.company_name = get_stock_price(self.stock_code.get())[1]
        
        if not data:
            self.update_today_info("N/A", [])
            self.update_plot_with_period(None)
            self.last_update_label.config(text="마지막 업데이트 시간: N/A")
            log_message("WARNING", "데이터가 없어 UI를 '데이터 없음' 상태로 업데이트합니다.")
            return
            
        last_data = data[-1]
        last_price = last_data['price']
        
        self.last_update_label.config(text=f"마지막 업데이트 시간: {last_data['timestamp'].strftime('%Y-%m-%d %H:%M')}")

        periods_analysis = []
        periods_str = self.periods.get().strip()
        if periods_str:
            periods_list = sorted([int(p) for p in periods_str.split(',') if p.strip().isdigit()])

            for period in periods_list:
                if len(data) >= period:
                    recent_data = data[-period:]
                    prices = [d['price'] for d in recent_data]
                    max_price = max(prices)
                    min_price = min(prices)
                    
                    pct_of_max = (1 - last_price / max_price) * 100 if max_price != 0 else 0
                    pct_of_min = (last_price / min_price - 1) * 100 if min_price != 0 else 0

                    periods_analysis.append({
                        'period': period,
                        'max_price': max_price,
                        'min_price': min_price,
                        'pct_of_max': pct_of_max,
                        'pct_of_min': pct_of_min
                    })
                else:
                    periods_analysis.append({
                        'period': period,
                        'max_price': 'N/A',
                        'min_price': 'N/A',
                        'pct_of_max': 'N/A',
                        'pct_of_min': 'N/A'
                    })
        self.update_today_info(last_price, periods_analysis)
        self.update_plot_with_period(None)
        log_message("SUCCESS", "GUI 업데이트 완료.")
    
    def setup_plot_tab(self, parent_frame):
        log_message("INFO", "시각화 탭 UI를 재구성합니다.")
        for widget in parent_frame.winfo_children():
            widget.destroy()

        main_frame = ttk.Frame(parent_frame)
        main_frame.pack(fill='both', expand=True)
        main_frame.grid_columnconfigure(0, weight=3)
        main_frame.grid_columnconfigure(1, weight=1)
        
        plot_area_frame = ttk.Frame(main_frame)
        plot_area_frame.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)

        period_buttons_frame = ttk.Frame(plot_area_frame)
        period_buttons_frame.pack(fill='x', padx=5, pady=5)
        ttk.Button(period_buttons_frame, text="전체 기간 보기", command=lambda: self.update_plot_with_period(None)).pack(side='left', padx=5)
        
        periods_list = [int(p) for p in self.periods.get().split(',') if p.strip().isdigit()]
        for p in periods_list:
            ttk.Button(period_buttons_frame, text=f'최근 {p}일 데이터', command=lambda period=p: self.update_plot_with_period(period)).pack(side='left', padx=5)

        self.fig = Figure(figsize=(5, 4), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_area_frame)
        self.canvas.draw()
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(fill='both', expand=True, padx=5, pady=5)

        control_area_frame = ttk.Frame(main_frame)
        control_area_frame.grid(row=0, column=1, sticky='nsew', padx=(10, 0))
        
        today_info_frame = ttk.LabelFrame(control_area_frame, text="오늘의 주가 분석", padding=10)
        today_info_frame.pack(fill='both', expand=True, pady=5, padx=5)

        self.last_update_label = ttk.Label(today_info_frame, text="마지막 업데이트 시간: N/A", font=("Helvetica", 10))
        self.last_update_label.pack(anchor='w')
        self.current_price_label = ttk.Label(today_info_frame, text="현재 가격: N/A", font=("Helvetica", 12, "bold"))
        self.current_price_label.pack(anchor='w', pady=(0, 10))
        
        self.today_info_widgets = {}
        periods_list = sorted([int(p) for p in self.periods.get().split(',') if p.strip().isdigit()])
        
        for period in periods_list:
            frame = ttk.Frame(today_info_frame)
            frame.pack(fill='x', pady=2)
            
            period_label = ttk.Label(frame, text=f"--- 최근 {period}일 데이터 ---", font=("Helvetica", 10, "bold"))
            period_label.pack(anchor='w')
            
            max_label = ttk.Label(frame, text="", font=("Helvetica", 10))
            max_label.pack(anchor='w')
            
            min_label = ttk.Label(frame, text="", font=("Helvetica", 10))
            min_label.pack(anchor='w')
            
            pct_max_label = ttk.Label(frame, text="", font=("Helvetica", 10))
            pct_max_label.pack(anchor='w')
            
            pct_min_label = ttk.Label(frame, text="", font=("Helvetica", 10))
            pct_min_label.pack(anchor='w')
            
            self.today_info_widgets[period] = {
                'max': max_label,
                'min': min_label,
                'pct_max': pct_max_label,
                'pct_min': pct_min_label
            }

    def update_today_info(self, current_price, periods_analysis):
        """오늘 날짜의 분석 정보를 GUI에 업데이트합니다."""
        if isinstance(current_price, int):
            self.current_price_label.config(text=f"현재 가격: {current_price:,}원")
        else:
            self.current_price_label.config(text=f"현재 가격: {current_price}원")

        for period_data in periods_analysis:
            period = period_data['period']
            max_price = period_data['max_price']
            min_price = period_data['min_price']
            pct_of_max = period_data['pct_of_max']
            pct_of_min = period_data['pct_of_min']
            
            if period in self.today_info_widgets:
                widgets = self.today_info_widgets[period]
                
                if isinstance(max_price, (int, float)):
                    widgets['max'].config(text=f"최고가: {max_price:,}원")
                    if current_price == max_price:
                        widgets['pct_max'].config(text="현재 최고가", foreground="red")
                    elif isinstance(pct_of_max, (int, float)):
                        widgets['pct_max'].config(text=f"최고가 대비: {pct_of_max:.2f}%▼")
                        widgets['pct_max'].config(foreground="blue" if pct_of_max < 1.0 else "black")
                    else:
                        widgets['pct_max'].config(text="최고가 대비: 데이터 부족", foreground="black")
                else: 
                    widgets['max'].config(text=f"최고가: {max_price}")
                    widgets['pct_max'].config(text="최고가 대비: 데이터 부족", foreground="black")

                if isinstance(min_price, (int, float)):
                    widgets['min'].config(text=f"최저가: {min_price:,}원")
                    if current_price == min_price:
                        widgets['pct_min'].config(text="현재 최저가", foreground="blue")
                    elif isinstance(pct_of_min, (int, float)):
                        widgets['pct_min'].config(text=f"최저가 대비: {pct_of_min:.2f}%▲")
                        widgets['pct_min'].config(foreground="red" if pct_of_min < 1.0 else "black")
                    else:
                        widgets['pct_min'].config(text="최저가 대비: 데이터 부족", foreground="black")
                else:
                    widgets['min'].config(text=f"최저가: {min_price}")
                    widgets['pct_min'].config(text="최저가 대비: 데이터 부족", foreground="black")

    def update_period_combos(self, *args):
        periods_str = self.periods.get()
        periods_list = [p.strip() for p in periods_str.split(',') if p.strip().isdigit()]
        
        for condition in self.alert_conditions:
            condition['combo']['values'] = periods_list
            if condition['period'].get() not in periods_list and periods_list:
                condition['period'].set(periods_list[0])
            elif not periods_list:
                condition['period'].set('')

    def add_alert_condition(self):
        if len(self.alert_conditions) >= 5:
            messagebox.showwarning("제한", "알림 조건은 최대 5개까지 추가할 수 있습니다.")
            return

        frame = ttk.Frame(self.alert_frame, padding=5, relief='solid', borderwidth=1)
        frame.pack(fill='x', padx=5, pady=5)

        period_var = tk.StringVar()
        max_pct_var = tk.StringVar(value='5.0')
        min_pct_var = tk.StringVar(value='5.0')

        ttk.Label(frame, text="분석 기간 (일 단위):").grid(row=0, column=0, sticky='w', padx=5, pady=5)
        period_combo = ttk.Combobox(frame, textvariable=period_var, state="readonly")
        period_combo.grid(row=0, column=1, sticky='ew', padx=5, pady=5)

        ttk.Label(frame, text="최고가 대비 하락률 (%):").grid(row=1, column=0, sticky='w', padx=5, pady=5)
        ttk.Entry(frame, textvariable=max_pct_var).grid(row=1, column=1, sticky='ew', padx=5, pady=5)
        ttk.Label(frame, text="이하일 때 알림").grid(row=1, column=2, sticky='w', padx=5, pady=5)

        ttk.Label(frame, text="최저가 대비 상승률 (%):").grid(row=2, column=0, sticky='w', padx=5, pady=5)
        ttk.Entry(frame, textvariable=min_pct_var).grid(row=2, column=1, sticky='ew', padx=5, pady=5)
        ttk.Label(frame, text="이하일 때 알림").grid(row=2, column=2, sticky='w', padx=5, pady=5)
        
        frame.grid_columnconfigure(1, weight=1)
        
        self.alert_conditions.append({
            'frame': frame,
            'period': period_var,
            'max_pct': max_pct_var,
            'min_pct': min_pct_var,
            'combo': period_combo
        })
        
        self.update_period_combos()

    def remove_alert_condition(self):
        if len(self.alert_conditions) > 1:
            last_condition = self.alert_conditions.pop()
            last_condition['frame'].destroy()
        else:
            messagebox.showwarning("제한", "최소 1개의 알림 조건은 필수입니다.")

    def browse_file_path(self):
        filename = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if filename:
            self.file_path.set(filename)
        self.load_and_display_data()

    def update_plot_with_period(self, period_to_show):
        file_path = self.file_path.get()
        data = get_historical_prices_from_csv(file_path)
        
        self.ax.clear()
        
        if not data:
            self.ax.set_title("데이터 파일이 없습니다.")
            self.canvas.draw()
            return

        if period_to_show is not None and len(data) >= period_to_show:
            data = data[-period_to_show:]
            title_text = f"{self.company_name}({self.stock_code.get()}) 주가 추이 (최근 {period_to_show}일)"
        else:
            title_text = f"{self.company_name}({self.stock_code.get()}) 주가 추이 (전체)"

        timestamps = [d['timestamp'] for d in data]
        prices = [d['price'] for d in data]

        self.ax.plot(timestamps, prices, label='주가', marker='o', markersize=3)
        
        if len(prices) > 0:
            max_price = max(prices)
            min_price = min(prices)
            self.ax.axhline(y=max_price, color='r', linestyle='--', label=f'기간 내 최고가 ({max_price:,})')
            self.ax.axhline(y=min_price, color='b', linestyle='--', label=f'기간 내 최저가 ({min_price:,})')
            self.ax.legend()

        self.ax.set_title(title_text)
        self.ax.set_xlabel("날짜 및 시간")
        self.ax.set_ylabel("가격")
        
        # 수정된 부분: 시간도 표시되도록 포맷 변경
        formatter = mdates.DateFormatter('%Y-%m-%d %H:%M')
        self.ax.xaxis.set_major_formatter(formatter)
        
        self.fig.autofmt_xdate()
        
        self.ax.grid(True)
        self.canvas.draw()

# ====================================================================
# C. 메인 실행
# ====================================================================

if __name__ == "__main__":
    app = StockApp()
    app.mainloop()