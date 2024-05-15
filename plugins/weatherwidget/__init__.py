import shutil
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Dict, Tuple, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from playwright.sync_api import sync_playwright
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.plugin import PluginManager
from app.log import logger
from app.plugins import _PluginBase
from app.utils.http import RequestUtils

lock = threading.Lock()
scheduler_lock = threading.Lock()

SCREENSHOT_DEVICES = {
    "default": {
        "mobile": {
            "device": "iPhone 13 Pro Max",
            "size": {}
        },
        "desktop": {
            "device": "iPad Pro 11",
            "size": {'width': 740, 'height': 1024}
        }
    },
    "border": {
        "mobile": {
            "device": "iPhone 13 Pro Max",
            "size": {}
        },
        "desktop": {
            "device": "iPad Pro 11",
            "size": {}
        }
    }
}

IMAGES_PATH = settings.CONFIG_PATH / "temp" / "WeatherWidget" / "images"
IMAGES_PATH.mkdir(parents=True, exist_ok=True)
WEATHER_API_KEY = "bdd98ec1d87747f3a2e8b1741a5af796"


class WeatherWidget(_PluginBase):
    # region 全局定义

    # 插件名称
    plugin_name = "天气"
    # 插件描述
    plugin_desc = "支持在仪表盘中显示实时天气小部件。"
    # 插件图标
    plugin_icon = "https://github.com/InfinityPacer/MoviePilot-Plugins/raw/main/icons/weatherwidget.png"
    # 插件版本
    plugin_version = "1.3"
    # 插件作者
    plugin_author = "InfinityPacer"
    # 作者主页
    author_url = "https://github.com/InfinityPacer"
    # 插件配置项ID前缀
    plugin_config_prefix = "weatherwidget_"
    # 加载顺序
    plugin_order = 80
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    # enable
    _enabled = None
    # border
    _border = None
    # clear_cache
    _clear_cache = None
    # location
    _location = None
    # weather_url
    _weather_url = None
    # location_url
    _location_url = None
    # last_screenshot_time
    _last_screenshot_time = None
    # min_screenshot_span
    _min_screenshot_span = 5 * 60
    # 截图超时时间
    _screenshot_timeout = 2 * 60
    # 截图类型
    _screenshot_type = None
    # 天气刷新间隔
    _refresh_interval = 1
    # 定时器
    _scheduler = None
    # 退出事件
    _event = threading.Event()

    # endregion

    def init_plugin(self, config: dict = None):
        if not config:
            return

        self.stop_service()

        self._enabled = config.get("enabled", False)
        self._border = config.get("border", False)
        self._clear_cache = config.get("clear_cache", False)
        self._location = config.get("location", "")
        self._location_url = config.get("location_url", "")
        self._last_screenshot_time = None
        self._screenshot_type = self.__get_screenshot_type()

        if self._clear_cache:
            self.__save_data({})
            self.__clear_image()

        self.__update_config()

        if not self._enabled:
            return

        if not self._location:
            logger.error("城市不能为空")
            return

        if not self.__check_image():
            logger.info("没有找到截图，立即执行一次截图任务")
            self.__add_screenshot_task()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
            定义远程控制命令
            :return: 命令关键字、事件、描述、附带数据
            """
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """
        获取插件API
        [{
            "path": "/xx",
            "endpoint": self.xxx,
            "methods": ["GET", "POST"],
            "summary": "API说明"
        }]
        """

        return [{
            "path": "/image",
            "endpoint": self.invoke_service,
            "methods": ["GET"],
            "summary": "获取天气图片",
            "description": "获取天气图片",
        }]

    def __get_total_elements(self) -> List[dict]:
        """
        组装汇总元素
        """

        if self._border:
            return [
                {
                    'component': 'VCardItem',
                    'content': [
                        {
                            'component': 'VCardTitle',
                            'text': f"{self._location}"
                        }
                    ]
                },
                {
                    'component': 'VImg',
                    'props': {
                        'src': f'/api/v1/plugin/WeatherWidget/image?'
                               f'location={self._location}&apikey={settings.API_TOKEN}&t={datetime.now().timestamp()}',
                        'height': 'auto',
                        'max-width': '100%',
                        'width': '100%',
                        'cover': True,
                    }
                }
            ]
        else:
            return [
                {
                    'component': 'VCardItem',
                    'props': {
                        'class': 'w-full',
                        'style': {
                            'position': 'relative',
                            'height': 'auto',
                            'background': 'linear-gradient(225deg, #fee5ca, #e9f0ff 55%, #dce3fb)',
                            'padding': "0 0 1.25rem"
                        }
                    },
                    'content': [
                        {
                            'component': 'VImg',
                            'props': {
                                'src': f'/api/v1/plugin/WeatherWidget/image?'
                                       f'location={self._location}&apikey={settings.API_TOKEN}&t={datetime.now().timestamp()}',
                                'height': '310px',
                                'max-width': '100%',
                                'width': '100%',
                                'cover': True,
                            }
                        },
                        {
                            'component': 'VCardText',
                            'props': {
                                'class': 'v-card-text w-full flex flex-row justify-start items-start absolute '
                                         'top-0 left-0 cursor-pointer',
                                'style': {
                                    'padding': '1.25rem'
                                }
                            },
                            'content': [
                                {
                                    'component': 'span',
                                    'props': {
                                        'class': 'mb-1 font-bold line-clamp-2 overflow-hidden text-ellipsis ...',
                                        'style': {
                                            'color': 'black',
                                            'font-size': '1.25rem',
                                            'line-wight': '2rem',
                                            'font-wight': '500',
                                        }
                                    },
                                    'text': self._location
                                }
                            ]
                        }
                    ]
                }
            ]

    def get_dashboard(self) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
        """
        获取插件仪表盘页面，需要返回：1、仪表板cols配置字典；2、全局配置（自动刷新等）；2、仪表板页面元素配置json（含数据）
        1、col配置参考：
        {
            "cols": 12, "md": 6
        }
        2、全局配置参考：
        {
            "refresh": 10, // 自动刷新时间，单位秒
            "border": True, // 是否显示边框，默认True，为False时取消组件边框和边距，由插件自行控制
        }
        3、页面配置使用Vuetify组件拼装，参考：https://vuetifyjs.com/
        """
        exist_images = self.__check_image()

        # 列配置
        cols = {
            "cols": 12,
            "md": 4
        }
        # 全局配置
        attrs = {
            "border": not exist_images
        }

        # 拼装页面元素
        if not exist_images:
            elements = [
                {
                    'component': 'VCardItem',
                    'content': [
                        {
                            'component': 'div',
                            'text': '暂无数据',
                            'props': {
                                'class': 'text-center'
                            }
                        }
                    ]
                }
            ]
        else:
            elements = self.__get_total_elements()
        return cols, attrs, elements

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {

                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        },
                                    }
                                ],
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'border',
                                            'label': '显示边框',
                                        },
                                    }
                                ],
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'clear_cache',
                                            'label': '清理缓存',
                                        },
                                    }
                                ],
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'location',
                                            'label': '城市',
                                            'placeholder': '城市地点',
                                        },
                                    }
                                ],
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'location_url',
                                            'label': '城市链接',
                                            'placeholder': '和风天气的城市天气链接',
                                        },
                                    }
                                ],
                            },
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '注意：因涉及新增API，安装/更新插件后需重启Docker后生效'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '注意：通过在和风天气官网获取对应链接精确定位城市，如「秦淮区」的链接为'
                                                    'https://www.qweather.com/weather/qinhuai-101190109.html，'
                                                    '则在城市链接填写 qinhuai-101190109'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '注意：数据异常时，可通过填写城市链接精确定位城市'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '天气数据来源于 '
                                        },
                                        'content': [
                                            {
                                                'component': 'a',
                                                'props': {
                                                    'href': 'https://www.qweather.com',
                                                    'target': '_blank'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'u',
                                                        'text': '和风天气'
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'span',
                                                'text': '，再次感谢和风天气（https://www.qweather.com）提供的服务'
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "border": False
        }

    def get_page(self) -> List[dict]:
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        if self._enabled:
            return [{
                "id": "RefreshWeather",
                "name": "定时获取天气信息",
                "trigger": "interval",
                "func": self.__take_screenshots,
                "kwargs": {"hours": self._refresh_interval}
            }]
        return []

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    # self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            logger.info(str(e))

    def __update_config(self):
        """保存插件配置"""
        self.update_config(
            {
                "enabled": self._enabled,
                "border": self._border,
                "location": self._location,
                "location_url": self._location_url
            })

    def invoke_service(self, request: Request, location: str, apikey: str) -> Any:
        """invokeService"""
        return PluginManager().run_plugin_method(self.__class__.__name__, "get_weather_image", **{
            "request": request,
            "location": location,
            "apikey": apikey
        })

    def get_weather_image(self, request: Request, location: str, apikey: str) -> Any:
        """读取图片"""

        if apikey != settings.API_TOKEN:
            return None
        if not location:
            logger.error("没有地址信息，获取天气图片失败")
            return None
        # 每次请求时，获取一次最新的图片信息
        self.__add_screenshot_task()
        # 获取UA
        user_agent = request.headers.get('user-agent', 'Unknown User-Agent')
        key = self.detect_device_type(user_agent=user_agent).lower()
        # 这里实际上返回的是上一次的图片信息
        path_obj = self.__get_latest_image(key=key)
        if not path_obj:
            return None
        if not path_obj.exists():
            return None
        if not path_obj.is_file():
            return None
        # 判断是否图片文件
        if path_obj.suffix.lower() not in [".jpg", ".png", ".gif", ".bmp", ".jpeg", ".webp"]:
            return None
        return Response(content=path_obj.read_bytes(), media_type="image/jpeg")

    def __add_screenshot_task(self):
        """添加截图任务"""
        if not self._enabled:
            return

        if not self._scheduler:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)

        if len(self._scheduler.get_jobs()):
            logger.info("已经存在待执行的截图任务，清空任务并继续添加")
            self._scheduler.remove_all_jobs()

        self._scheduler.add_job(
            func=self.__take_screenshots,
            trigger="date",
            run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
            name="获取一次天气信息",
        )
        logger.info("已添加截图任务，等待执行")
        if self._scheduler.get_jobs():
            self._scheduler.print_jobs()
        if not self._scheduler.running:
            self._scheduler.start()

    def __update_with_log_screenshot_time(self, current_time: Optional[datetime]):
        """更新截图时间"""
        self._last_screenshot_time = current_time
        if current_time:
            logger.info(
                f"截图记录更新，最后一次截图时间重置为 {self._last_screenshot_time.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            logger.info(f"截图记录更新，发生错误，最后一次截图时间重置为None")

    def __take_screenshots(self):
        """管理多设备截图任务"""
        IMAGES_PATH.mkdir(parents=True, exist_ok=True)
        current_time = datetime.now(tz=pytz.timezone(settings.TZ))
        if self._last_screenshot_time:
            time_since_last = (current_time - self._last_screenshot_time).total_seconds()
            time_to_wait = self._min_screenshot_span - time_since_last
            if time_since_last < self._min_screenshot_span:
                logger.info(f"截图过快，最小截图间隔为 {self._min_screenshot_span} 秒。请在 {time_to_wait:.2f} 秒后重试。")
                return

        self.__update_with_log_screenshot_time(current_time=current_time)

        self._weather_url = self.__get_weather_url()
        if not self._weather_url:
            logger.error("无法获取天气请求地址，请检查配置")
            self.__update_with_log_screenshot_time(current_time=None)
            return

        try:
            with sync_playwright() as playwright:
                start_time = datetime.now()
                logger.info("正在准备截图服务，playwright服务启动中")
                self.__update_with_log_screenshot_time(current_time=current_time)
                screenshot_devices = self.__get_screenshot_device()
                if not screenshot_devices:
                    logger.error("获取截图设备失败，请检查")
                with playwright.chromium.launch(headless=True, proxy=settings.PROXY_SERVER) as browser:
                    for key, device in screenshot_devices.items():
                        try:
                            logger.info(f'{key} 正在启动 screenshot ...')
                            self.__screenshot_element(playwright=playwright, browser=browser, key=key, device=device)
                            elapsed_time = datetime.now() - start_time
                            logger.info(f'运行完毕，用时 {elapsed_time.total_seconds()} 秒')
                        except Exception as e:
                            logger.error(f"screenshot_element failed: {str(e)}")
        except Exception as e:
            logger.error(f"take_screenshots failed: {str(e)}")

    def __screenshot_element(self, playwright, browser, key: str, device: dict):
        """执行单个截图任务"""
        current_time = datetime.now(tz=pytz.timezone(settings.TZ))
        timestamp = current_time.strftime("%Y%m%d%H%M%S")
        selector = ".c-city-weather-current"
        image_path = IMAGES_PATH / f"{self.__get_screenshot_image_pre_path(key=key)}_{timestamp}.png"

        logger.info(f"开始加载 {key} 页面: {self._weather_url}")
        self.__update_with_log_screenshot_time(current_time=current_time)
        logger.info(playwright.devices)
        with browser.new_context(**playwright.devices[device.get("device")]) as context:
            with context.new_page() as page:
                try:
                    size = device.get("size")
                    if size:
                        page.set_viewport_size(device.get("size"))
                    page.goto(self._weather_url)
                    page.wait_for_selector(selector, timeout=self._screenshot_timeout * 1000)
                    logger.info(f"{key} 页面加载成功，标题: {page.title()}")
                    self.__update_with_log_screenshot_time(current_time=datetime.now(tz=pytz.timezone(settings.TZ)))
                    element = page.query_selector(selector)
                    if element:
                        # 获取元素的位置和尺寸
                        box = element.bounding_box()
                        if box:
                            # 计算新的裁剪区域，每边缩进8px，从而避免border-radius
                            clip = {
                                "x": box["x"] + 6,
                                "y": box["y"] + 6,
                                "width": box["width"] - 12,
                                "height": box["height"] - 12
                            }
                            # 截图并保存
                            # element.screenshot(path=image_path)
                            page.screenshot(path=image_path, clip=clip)
                            logger.info(f"{key} 截图成功，截图路径: {image_path}")
                        else:
                            element.screenshot(path=image_path)
                            logger.info(f"{key} 截图成功，截图路径: {image_path}")
                        self.__manage_images(key=key)
                        self.__update_with_log_screenshot_time(current_time=datetime.now(tz=pytz.timezone(settings.TZ)))
                    else:
                        logger.warning(f"{key} 未找到指定的选择器: {selector}")
                        self.__update_with_log_screenshot_time(current_time=None)
                except Exception as e:
                    logger.error(f"{key} 截图失败，URL: {self._weather_url}, 错误：{e}")
                    self.__update_with_log_screenshot_time(current_time=None)

    def __manage_images(self, key: str, max_files: int = 5):
        """管理图片文件，确保每种类型最多保留 max_files 张"""
        files = sorted(IMAGES_PATH.glob(f"{self.__get_screenshot_image_pre_path(key=key)}_*.png"),
                       key=lambda x: x.stat().st_mtime)
        if len(files) > max_files:
            for file in files[:-max_files]:
                file.unlink()
                logger.info(f"删除旧图片: {file}")

    def __check_image(self) -> bool:
        """判断是否存在图片"""
        files_exist = any(IMAGES_PATH.glob(f"{self.__get_screenshot_image_pre_path()}_*.png"))
        if not files_exist:
            logger.error("没有找到图片信息")
        return files_exist

    def __get_latest_image(self, key: str) -> Optional[Path]:
        """获取指定key的最新图片路径"""
        # 搜索所有匹配的图片文件，并按修改时间排序
        try:
            latest_image = max(IMAGES_PATH.glob(f"{self.__get_screenshot_image_pre_path(key=key)}_*.png"),
                               key=lambda x: x.stat().st_mtime)
            return latest_image
        except ValueError:
            logger.error(f"{key}: 没有找到图片信息")
            return None

    @staticmethod
    def __get_weather_api_key() -> str:
        """获取天气api密钥"""
        return WEATHER_API_KEY

    def __get_weather_url(self) -> Optional[str]:
        """获取天气Url"""
        if not self._location:
            logger.error("没有配置城市，无法获取对应的城市天气链接")
            return None

        if self._location_url:
            return f"https://www.qweather.com/weather/{self._location_url}.html"

        location_map = self.get_data("location")
        if location_map:
            weather_url = location_map.get(self._location, {}).get("fxLink")
            if weather_url:
                return weather_url
        else:
            location_map = {}

        url = (f"https://geoapi.qweather.com/v2/city/lookup?"
               f"key={self.__get_weather_api_key()}&location={self._location}&lang=zh")

        response = RequestUtils().get_res(url)
        logger.info(f"请求和风天气获取详情信息：{url}")
        logger.info(f"响应信息: {response.text}")

        if response.status_code != 200:
            logger.error(f"连接和风天气失败, 状态码: {response.status_code}")
            return None
        else:
            data = response.json()
            if data.get('code') == "200":
                remote_locations = data.get('location', [])
                if remote_locations:
                    first = remote_locations[0]
                    weather_url = first.get("fxLink")
                    logger.info(f"城市: {self._location} 获取到对应的城市天气链接为: {weather_url}")
                    if weather_url:
                        location_map[self._location] = first
                        self.__save_data(location_map)
                        return weather_url

        logger.error(f"连接和风天气成功, 但获取详情信息失败")
        return None

    def __save_data(self, data: dict):
        """保存插件数据"""
        self.save_data("location", data)

    @staticmethod
    def __clear_image():
        """清理缓存图片"""
        # 检查目录是否存在
        if IMAGES_PATH.exists():
            # 删除目录及其所有内容
            shutil.rmtree(IMAGES_PATH)
            logger.info(f"目录 {IMAGES_PATH} 已清理")
        else:
            logger.info(f"目录 {IMAGES_PATH} 不存在")

    @staticmethod
    def detect_device_type(user_agent: str) -> str:
        """根据UA获取设备类型"""
        logger.info(f"detect_device_type user_agent: {user_agent}")
        # 定义移动设备的关键字列表
        mobile_keywords = ['Mobile', 'Android', 'iPhone', 'iPad']

        # 检查UA中是否包含移动设备的关键字
        for keyword in mobile_keywords:
            if keyword in user_agent:
                logger.info(f"当前访问设备类型为 Mobile")
                return 'Mobile'

        logger.info(f"当前访问设备类型为 Desktop")
        return 'Desktop'

    def __get_screenshot_type(self):
        """获取截图类型"""
        return "border" if self._border else "default"

    def __get_screenshot_device(self) -> Optional[dict]:
        """获取截图设备信息"""
        screenshot_type = self._screenshot_type
        screenshot_devices = SCREENSHOT_DEVICES.get(screenshot_type)
        return screenshot_devices

    def __get_screenshot_image_pre_path(self, key: str = None) -> str:
        """获取截图前置路径"""
        image_path = f"weather_{self._location}_{self._screenshot_type}"
        return f"{image_path}_{key}" if key else image_path
