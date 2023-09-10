# 通用sqlite工具
# 用于插件管理或游戏等数据储存
# 2023.9.9 @bread233
import sqlite3
import os
from nonebot.log import logger

data_path = os.path.join(os.path.abspath(__file__), "../../../data/db")


class DBManage:
    # 初始化DB
    # 需要传入DB名
    # db_name : DB名
    def __init__(self, db_name):
        if db_name is None:
            raise ValueError("数据库名不能为空!")
        self.db_name = db_name
        self.DB_path = os.path.join(data_path, f"{db_name}.db")
        if not os.path.exists(data_path):
            os.makedirs(data_path)
        self.conn = sqlite3.connect(self.DB_path)

    # 新建表
    # 需要传入字典形式参数
    # TBL : 表名
    # COLUMS : 字典参数
    # 例:COLUMS = dict(NO="INTEGER PRIMARY KEY UNIQUE", USERID="TEXT", BREAD_NUM="INTEGER")
    #    create(TBL = "BREAD_TBL", COLUMS = dict(NO="INTEGER PRIMARY KEY UNIQUE", USERID="TEXT", BREAD_NUM="INTEGER"))
    def create(self, TBL, COLUMS):
        c = self.conn.cursor()
        if TBL is None:
            raise ValueError("表名不能为空!")
        if len(COLUMS) <= 0 or COLUMS is None:
            raise ValueError("请设置表格的各项数据名及其类型,设置方法:dict(数据=='类型')")
        sql = []
        sql.append(f"CREATE TABLE IF NOT EXISTS {TBL} (")
        keys = []
        for key, value in COLUMS.items():
            keys.append(f"{key}            {value}")
        keys = ",\n".join(keys)
        sql.append(keys)
        sql.append(");")
        sql = "\n".join(sql)
        print(sql)
        try:
            c.execute(sql)
            self.conn.commit()
            logger.info(
                f"""创建表格{TBL}成功
SQL:{sql}"""
            )
        except Exception as e:
            logger.error(f"创建表格出错: {e}")

    # 插入数据
    # 需要传入字典形式参数
    # TBL : 表名
    # COLUMS : 字典参数
    # 例:COLUMS = dict(NO=1, USERID="123456", BREAD_NUM=5)
    #    insert(TBL = "BREAD_TBL", COLUMS = dict(NO=1, USERID="123456", BREAD_NUM=5))
    def insert(self, TBL, COLUMS):
        c = self.conn.cursor()
        if TBL is None:
            raise ValueError("表名不能为空!")
        if len(COLUMS) <= 0 or COLUMS is None:
            raise ValueError("请设置表格的各项数据名及其数据,设置方法:dict(数据名=='数据')")
        sql = []
        keys = []
        values = []
        sql.append(f"INSERT OR REPLACE INTO {TBL} ")
        for key, value in COLUMS.items():
            keys.append(key)
            values.append(str(value))
        keys_ = ",".join(keys)
        keys = "(" + keys_ + ")"
        values_ = ",".join(values)
        values = " VALUES (" + values_ + ");"
        sql.append(keys)
        sql.append(values)
        sql = "\n".join(sql)
        sql = sql.replace("'None'", "null").replace("None", "null")
        try:
            c.execute(sql)
            self.conn.commit()
            logger.info(
                f"""插入表{TBL}数据成功
SQL:{sql}"""
            )
        except Exception as e:
            logger.error(f"插入数据出错: {e}")
            logger.error(f"SQL:{sql}")

    # 删除数据
    # 需要传入字典形式参数
    # TBL : 表名
    # COLUMS : 字典参数
    # 例:COLUMS = dict(NO=1, USERID="123456", BREAD_NUM=5)
    #    delete(TBL = "BREAD_TBL", COLUMS = dict(NO=1, USERID="123456", BREAD_NUM=5))
    def delete(self, TBL, COLUMS=None):
        c = self.conn.cursor()
        if TBL is None:
            raise ValueError("表名不能为空!")
        if COLUMS is None:
            sql = f"DELETE FROM {TBL};"
            try:
                c.execute(sql)
                self.conn.commit()
                logger.info(
                    f"""删除表{TBL}数据成功
SQL:{sql}"""
                )
                return
            except Exception as e:
                logger.error(f"删除数据出错: {e}")
                logger.error(f"SQL:{sql}")
                return
        sql = []
        where = []
        sql.append(f"DELETE FROM {TBL} WHERE ")
        for key, value in COLUMS.items():
            where.append(f" {key} = {value} ")
        where = " AND ".join(where)
        sql.append(where)
        sql = "\n".join(sql) + ";"
        sql = sql.replace("'None'", "null").replace("None", "null")
        try:
            c.execute(sql)
            self.conn.commit()
            logger.info(
                f"""删除表{TBL}数据成功
SQL:{sql}"""
            )
        except Exception as e:
            logger.error(f"删除数据出错: {e}")
            logger.error(f"SQL:{sql}")

    # 修改数据
    # 需要传入字典形式参数
    # TBL : 表名
    # COLUMS_UPDATE : 字典参数
    # COLUMS_WHERE : 字典参数
    # 例:COLUMS_UPDATE = dict(USERID="34567", BREAD_NUM=0)
    # 例:COLUMS_WHERE = dict(NO=1)
    #    update(TBL = "BREAD_TBL", COLUMS_UPDATE = dict(USERID="34567", BREAD_NUM=0),COLUMS_WHERE = dict(NO=1))
    def update(self, TBL, COLUMS_UPDATE, COLUMS_WHERE):
        c = self.conn.cursor()
        if TBL is None:
            raise ValueError("表名不能为空!")
        if (
            len(COLUMS_UPDATE) <= 0
            or COLUMS_UPDATE is None
            or len(COLUMS_WHERE) <= 0
            or COLUMS_WHERE is None
        ):
            raise ValueError("请设置表格的各项数据名及其数据,dict(数据名=='数据')")
        sql = []
        update = []
        where = []
        sql.append(f"UPDATE {TBL} SET ")
        for key, value in COLUMS_UPDATE.items():
            update.append(f" {key} = {value} ")
        update = ",".join(update)
        sql.append(update)
        sql.append(" WHERE ")
        for key, value in COLUMS_WHERE.items():
            where.append(f" {key} = {value} ")
        where = " AND ".join(where)
        sql.append(where)
        sql = "\n".join(sql) + ";"
        sql = sql.replace("'None'", "null").replace("None", "null")
        try:
            c.execute(sql)
            self.conn.commit()
            logger.info(
                f"""修改表{TBL}数据成功
SQL:{sql}"""
            )
        except Exception as e:
            logger.error(f"修改数据出错: {e}")
            logger.error(f"SQL:{sql}")

    # 查询数据
    # 需要传入字典形式参数
    # TBL : 表名
    # COLUMS_SELECT : 数组参数 is None
    # COLUMS_WHERE : 字典参数 is None
    # 例:COLUMS_SELECT = ["USERID"]
    # 例:COLUMS_WHERE = dict(NO=1)
    #    select(TBL = "BREAD_TBL", COLUMS_SELECT = ["USERID"],COLUMS_WHERE = dict(NO=1))
    def select(self, TBL, COLUMS_SELECT=None, COLUMS_WHERE=None):
        c = self.conn.cursor()
        if TBL is None:
            raise ValueError("表名不能为空!")
        if COLUMS_SELECT is None and COLUMS_WHERE is None:
            sql = f"SELECT * FROM {TBL};"
            try:
                result = c.execute(sql).fetchall()
                logger.info(
                    f"""查询表{TBL}数据成功
SQL:{sql}
result {result}"""
                )
                return result
            except Exception as e:
                logger.error(f"查询数据出错: {e}")
                return None
        elif COLUMS_SELECT is None and COLUMS_WHERE is not None:
            sql = []
            sql.append(f"SELECT * FROM {TBL} WHERE ")
            where = []
            for key, value in COLUMS_WHERE.items():
                where.append(f" {key} = {value} ")
            where = " AND ".join(where)
            sql.append(where)
            sql = "\n".join(sql) + ";"
            sql = sql.replace("'None'", "null").replace("None", "null")
            try:
                result = c.execute(sql).fetchall()
                logger.info(
                    f"""查询表{TBL}数据成功
SQL:{sql}
result {result}"""
                )
                return result
            except Exception as e:
                logger.error(f"查询数据出错: {e}")
                logger.error(f"SQL:{sql}")
                return None
        elif COLUMS_SELECT is not None and COLUMS_WHERE is None:
            sql = []
            sql.append(f"SELECT ")
            select = []
            for colum in COLUMS_SELECT:
                select.append(colum)
            select = ",".join(select)
            sql.append(select)
            sql.append(f" FROM {TBL};")
            sql = "\n".join(sql)
            sql = sql.replace("'None'", "null").replace("None", "null")
            try:
                result = c.execute(sql).fetchall()
                logger.info(
                    f"""查询表{TBL}数据成功
SQL:{sql}
result {result}"""
                )
                return result
            except Exception as e:
                logger.error(f"查询数据出错: {e}")
                logger.error(f"SQL:{sql}")
                return None
        elif COLUMS_SELECT is not None and COLUMS_WHERE is not None:
            sql = []
            sql.append(f"SELECT ")
            select = []
            for colum in COLUMS_SELECT:
                select.append(colum)
            select = ",".join(select)
            sql.append(select)
            sql.append(f" FROM {TBL} WHERE ")
            where = []
            for key, value in COLUMS_WHERE.items():
                where.append(f" {key} = {value} ")
            where = " AND ".join(where)
            sql.append(where)
            sql = "\n".join(sql) + ";"
            sql = sql.replace("'None'", "null").replace("None", "null")
            try:
                result = c.execute(sql).fetchall()
                logger.info(
                    f"""查询表{TBL}数据成功
SQL:{sql}
result {result}"""
                )
                return result
            except Exception as e:
                logger.error(f"查询数据出错: {e}")
                logger.error(f"SQL:{sql}")
                return None
        else:
            logger.error(f"查询数据出错异常,可能是给的数据有问题哦,请查看数据")
            return None

    # 关闭本次sql连接
    def close(self):
        self.conn.close()


"""
# 测试用
if __name__ == "__main__":
    DB = DBManage("test")
    print("路径为:" + str(DB.DB_path))
    DB.create(
        TBL="BREAD_TBL",
        COLUMS=dict(
            NO="INTEGER PRIMARY KEY UNIQUE", USERID="TEXT", BREAD_NUM="INTEGER"
        ),
    )
    DB.insert(TBL="BREAD_TBL", COLUMS=dict(NO=1, USERID="123456", BREAD_NUM=5))
    DB.insert(TBL="BREAD_TBL", COLUMS=dict(NO=2, USERID="233333", BREAD_NUM=10))
    result1 = DB.select(TBL="BREAD_TBL", COLUMS_SELECT=["USERID"])
    print("数据1为:" + str(result1))

    result2 = DB.select(TBL="BREAD_TBL", COLUMS_SELECT=None, COLUMS_WHERE=dict(NO=1))
    print("修改前:" + str(result2))
    DB.update(
        TBL="BREAD_TBL",
        COLUMS_UPDATE=dict(USERID="34567", BREAD_NUM=0),
        COLUMS_WHERE=dict(NO=1),
    )
    result3 = DB.select(TBL="BREAD_TBL", COLUMS_SELECT=None, COLUMS_WHERE=dict(NO=1))
    print("修改后:" + str(result3))
"""
