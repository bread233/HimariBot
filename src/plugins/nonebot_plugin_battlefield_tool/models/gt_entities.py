from typing import List, Optional, Dict, Any

class PlayerStats:
    """
    对应 template.html 中 'd' 对象的数据结构。
    包含玩家的基本统计信息。
    """
    def __init__(self,
                 avatar: str, # 玩家头像URL
                 user_name: str, # 玩家用户名
                 rank_img: str, # 玩家等级图片URL
                 rank: str, # 玩家等级
                 hours_played: str, # 游戏时间（小时）
                 kills: int, # 击杀数
                 kill_death: str, # 击杀/死亡比
                 kills_per_minute: str, # 每分钟击杀数
                 headshots: str, # 爆头率
                 accuracy: str, # 命中率
                 revives: str, # 急救
                 head_shots_num: str, # 爆头数
                 longest_head_shot: str, # 最远爆头距离（米）
                 wins: str, # 胜利场次
                 highest_kill_streak: str): # 最高连杀数
        self.avatar = avatar
        self.user_name = user_name
        self.rank_img = rank_img
        self.rank = rank
        self.hours_played = hours_played
        self.kills = kills
        self.kill_death = kill_death
        self.kills_per_minute = kills_per_minute
        self.headshots = headshots
        self.accuracy = accuracy
        self.revives = revives
        self.head_shots_num = head_shots_num
        self.longest_head_shot = longest_head_shot
        self.wins = wins
        self.highest_kill_streak = highest_kill_streak

    @classmethod
    def from_gt_dict(cls, data: Dict[str, Any]):
        """从gt字典创建 PlayerStats 实例"""
        return cls(
            avatar=data.get("avatar", ""),
            user_name=data.get("userName", "N/A"),
            rank_img=data.get("rankImg", ""),
            rank=str(data.get("rank", 0)),
            hours_played=str(data.get("__hours_played", 0.0)), # 注意这里是 __hours_played
            kills=int(data.get("kills", 0)),
            kill_death=str(data.get("killDeath", 0.0)),
            kills_per_minute=str(round(data.get("killsPerMinute", 0.0), 2)),
            headshots=str(data.get("headshots", 0.0)),
            accuracy=str(data.get("accuracy", 0.0)),
            revives=str(data.get("revives", 0)),
            head_shots_num=str(data.get("headShots", 0)),
            longest_head_shot=str(data.get("longestHeadShot", 0.0)),
            wins=str(data.get("wins", 0)),
            highest_kill_streak=str(data.get("highestKillStreak", 0))
        )

    def to_llm_text(self) -> str:
        """预处理 PlayerStats 方便 llm 理解"""
        return f"""用户{self.user_name}生涯总共击杀{self.kills}名敌军，击杀死亡比值(K/D):{self.kill_death},平均每分钟击杀(KPM):{self.kills_per_minute}，胜场:{self.wins}，急救了{self.revives}位士兵，爆头率：{self.headshots},总游玩时间，{self.hours_played}小时，最高连杀{self.highest_kill_streak}。"""



    def __repr__(self):
        return f"PlayerStats(user_name='{self.user_name}', rank={self.rank}, ...)"


class Weapon:
    """
    对应 weapon_card.html 中 'w' 对象的数据结构。
    包含武器的详细信息。
    """
    def __init__(self,
                 name: str, # 武器名称
                 image: str, # 武器图片URL
                 kills: int, # 武器击杀数
                 headshotKills: int, # 爆头击杀数
                 shotsFired: int, # 击发数
                 shotsHit: int, # 命中数
                 headshots: str, # 爆头率
                 accuracy: str, # 命中率
                 kills_per_minute: str, # 武器每分钟击杀数
                 time_spent: str, # 武器装备时间（小时）
                 type: str): # 武器类型
        self.name = name
        self.image = image
        self.kills = kills
        self.headshotKills = headshotKills
        self.shotsFired = shotsFired
        self.shotsHit = shotsHit
        self.headshots = headshots
        self.accuracy = accuracy
        self.kills_per_minute = kills_per_minute
        self.time_spent = time_spent
        self.type = type

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        """从字典创建 Weapon 实例"""
        return cls(
            name=data.get("weaponName", "N/A"),
            image=data.get("image", ""),
            kills=int(data.get("kills", 0)),
            headshotKills=int(data.get("headshotKills", 0)),
            shotsFired=int(data.get("shotsFired", 0)),
            shotsHit=int(data.get("shotsHit", 0)),
            headshots=str(data.get("headshots", 0)),
            accuracy=str(data.get("accuracy", 0.0)),
            kills_per_minute=str(round(data.get("killsPerMinute", 0.0), 2)),
            time_spent=str(round(data.get("timeEquipped", 0.0) / 3600, 1)),
            type=data.get("type", "Unknown")
        )

    def to_llm_text(self,game) -> str:
        """预处理 Weapon 方便 llm 理解"""
        if game == "bf4":
            return f"""使用{self.type}{self.name}，总共击杀了{self.kills}名敌军，该武器平均每分钟击杀{self.kills_per_minute}，爆头率{self.headshots},命中率{self.accuracy}"""
        else:
            return f"""使用{self.type}{self.name}{self.time_spent}小时，总共击杀了{self.kills}名敌军，该武器平均每分钟击杀{self.kills_per_minute}，爆头率{self.headshots},命中率{self.accuracy}"""


    def __repr__(self):
        return f"Weapon(name='{self.name}', kills={self.kills}, ...)"


class Vehicle:
    """
    对应 vehicle_card.html 中 'v' 对象的数据结构。
    包含载具的详细信息。
    """
    def __init__(self,
                 name: str, # 载具名称
                 image: str, # 载具图片URL
                 kills: int, # 载具击杀数
                 destroyed: str, # 载具摧毁数
                 kills_per_minute: str, # 载具每分钟击杀数
                 time_spent: str, # 载具使用时间（小时）
                 type: str): # 载具类型
        self.name = name
        self.image = image
        self.kills = kills
        self.destroyed = destroyed
        self.kills_per_minute = kills_per_minute
        self.time_spent = time_spent
        self.type = type

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        """从字典创建 Vehicle 实例"""
        return cls(
            name=data.get("vehicleName", "N/A"),
            image=data.get("image", ""),
            kills=int(data.get("kills", 0)),
            destroyed=str(data.get("destroyed", 0)),
            kills_per_minute=str(round(data.get("killsPerMinute", 0.0), 2)),
            time_spent=str(round(data.get("timeIn", 0.0) / 3600, 1)),
            type=data.get("type", "Unknown")
        )

    def to_llm_text(self,game) -> str:
        """预处理 Vehicle 方便 llm 理解"""
        return f"""使用{self.type}{self.name},{self.time_spent}小时,总共击杀了{self.kills}名敌军,该载具平均每分钟击杀{self.kills_per_minute},摧毁了{self.destroyed}辆载具。"""


    def __repr__(self):
        return f"Vehicle(name='{self.name}', kills={self.kills}, ...)"


class Server:
    """
    对应 server_card.html 中 's' 对象的数据结构。
    包含服务器的详细信息。
    """
    def __init__(self,
                 name: str,  # 服务器名称
                 image: str,  # 服务器图片URL
                 current_map: str,  # 当前地图
                 mode: str,  # 游戏模式
                 server_info: str,  # 服务器详细信息
                 country: str,  # 服务器所在国家
                 ):
        self.name = name
        self.image = image
        self.current_map = current_map
        self.mode = mode
        self.server_info = server_info
        self.country = country

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        """从字典创建 Server 实例"""
        return cls(
            name=data.get("prefix", "N/A"),
            image=data.get("url", ""),
            current_map=Server._get_name_category(data.get("currentMap", "")),
            mode=Server._get_mode_category(data.get("mode", "Unknown").lower()),
            server_info=data.get("serverInfo", "0/0"),
            country=data.get("country", "Unknown"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """将 Server 实例转换为字典"""
        return {
            "name": self.name,
            "image": self.image,
            "current_map": self.current_map,
            "mode": self.mode,
            "server_info": self.server_info,
            "country": self.country,
        }

    @staticmethod
    def _get_mode_category(category_name):
        category_map = {
            "conquest": "征服",
            "conquest large": "大型征服",
            "conquest small": "小型征服",
            "domination": "阵地战",
            "rush": "突袭(突破)",
            "team deathmatch": "团队死斗",
            "squad deathmatch": "小队死斗",
            "obliteration": "拆除炸弹",
            "defuse": "爆破",
            "air superiority": "空中优势",
            "carrier assault": "航母突袭",
            "chain link": "环环相扣",
            "capture the flag": "夺旗",
            "gun master": "枪神",
            "squad obliteration": "爆破",
        }
        return category_map.get(category_name, category_name)


    @staticmethod
    def _get_name_category(category_name):
        category_map = {
            # 原版地图
            "Siege of Shanghai": " 上海之围 ",
            "Operation Locker": " 极地监狱 ",
            "Flood Zone": " 水乡泽国 ",
            "Golmud Railway": " 荒野游踪 ",
            "Paracel Storm": " 西沙风暴 ",
            "Lancang Dam": " 水坝风云 ",
            "Hainan Resort": " 度假胜地 ",
            "Dawnbreaker": " 破晓行动 ",
            "Rogue Transmission": " 广播中心 ",
            "Zavod 311": " 废弃工厂 ",
            "Zavod: Graveyard Shift": " 废弃工厂：大夜班 ",
            "Dragon Valley 2015": " 龙之谷2015 ",
            "Operation Outbreak": " 丛林计划 ",
            #中国崛起
            "Altai Range": " 阿尔泰山 ",
            "Dragon Pass": " 龙隘之战 ",
            "Guilin Peaks": " 桂林群山 ",
            "Silk Road": " 丝绸之路 ",
            #二次进击
            "Caspian Border 2014": " 里海边境2014 ",
            "Gulf of Oman 2014": " 阿曼湾2014 ",
            "Operation Metro 2014": " 地铁行动2014 ",
            "Firestorm 2014": " 火线风暴2014 ",
            #海军风暴
            "Lost Islands": " 失落岛屿 ",
            "Nansha Strike": " 南沙风暴 ",
            "Wave Breaker": " 消波礁岸 ",
            "Operation Mortar": " 迫击行动 ",
            #龙之獠牙
            "Lumphini Garden": " 隆披尼花园 ",
            "Pearl Market": " 红桥市场 ",
            "Propaganda": " 政宣广场 ",
            "Sunken Dragon": " 沉龙河畔 ",
            #最终反击
            "Giants of Karelia": " 卡雷利亚巨人 ",
            "Hammerhead": " 双髻鲨基地 ",
            "Hangar 21": "21 号机库 ",
            "Operation Whiteout": " 雪盲行动 ",
            #补充
            "GUILIN PEAKS": " 桂林群山 ",
            "SILK ROAD": " 丝绸之路 ",
        }
        return category_map.get(category_name, category_name)

    def __repr__(self):
        return f"Server(name='{self.name}', mode='{self.mode}', country='{self.country}')"
