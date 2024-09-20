import nonebot
from nonebot.adapters import Bot
from nonebot import on_command
from nonebot.params import CommandArg, RawCommand
from nonebot.adapters.onebot.v11 import Message, MessageEvent, Bot, Event
from nonebot.rule import to_me
from math import ceil, floor

sim_matcher = on_command("school_idol_mst_score", aliases={"/算分"}, priority=5)

@sim_matcher.handle()
async def score(bot: Bot, event: Event, args: Message = CommandArg(), cmd: Message = RawCommand()):
    try:
        Message = args.extract_plain_text().strip()
        list_status = Message.split()
        if(len(list_status)!=3):
            return await sim_matcher.send("参数给多(少)了或者多打空格了\n具体使用方法:/算分 500 1000 1100", at_sender=True)
        text = update_status(list_status[0],list_status[1],list_status[2])
        await sim_matcher.send(text, at_sender=True)
    except Exception as e:
        message = f"error:{e}\n出现错误可能参数数量不对或者空格为全角，也有可能单属性大于上限"
        await sim_matcher.finish(message, at_sender=True)


def update_status(Vo,Da,Vi):
    Vo = int(Vo)
    Da = int(Da)
    Vi = int(Vi)
    Vo = Vo if Vo else 0
    Da = Da if Da else 0
    Vi = Vi if Vi else 0

    if Vo > 1800 or Da > 1800 or Vi > 1800:
        return "单属性最大值大于当前版本上限！请检查后重试！"

    Sum_ = Vo + Da + Vi

    c = int(30)
    Vo = min(Vo + c, 1800)
    Da = min(Da + c, 1800)
    Vi = min(Vi + c, 1800)

    Sum = Vo + Da + Vi
    return update_score(Sum,Sum_)

def status_impact(sum_value):
    return floor(sum_value * 23 / 10)

def score_impact(score):
    return floor(
        range_value(0, 5000, score) * 3 / 10 +
        range_value(5000, 10000, score) * 15 / 100 +
        range_value(10000, 20000, score) * 8 / 100 +
        range_value(20000, 30000, score) * 4 / 100 +
        range_value(30000, 40000, score) * 2 / 100 +
        range_value(40000, float('inf'), score) * 1 / 100
    )

def update_score(Sum,Sum_):
    rank_score = int(1700)

    sum_value = int(Sum)
    sum_value = sum_value if sum_value else 0
    status_score = status_impact(sum_value)

    ranks = [14500,13000,11500,10000,8000,6000,5000,3000,0]
    scores = []
    for rank in ranks:
        scores.append(result_to_score(int(rank), rank_score, status_score))
    if scores[0] < 60000 and Sum > 3600:
        text = f"""
您的面板为
【{Sum_}】→【{Sum}】(+{Sum-Sum_})
S+评价(14500)还需要在最终试验中获得【{scores[0]}pt】
S评价(13000)还需要在最终试验中获得【{scores[1]}pt】
A+评价(11500)还需要在最终试验中获得【{scores[2]}pt】
"""
    else:
        text = f"""
您的面板为
【{Sum_}】→【{Sum}】(+{Sum - Sum_})
S评价(13000)还需要在最终试验中获得【{scores[1]}pt】
A+评价(11500)还需要在最终试验中获得【{scores[2]}pt】
A评价(10000)还需要在最终试验中获得【{scores[3]}pt】
"""

    return text.strip()

def result_to_score(result, rank_score, status_score):
    n = result - rank_score - status_score
    return ceil(
        range_value(0, score_impact(5000), n) * 10 / 3 +
        range_value(score_impact(5000), score_impact(10000), n) * 100 / 15 +
        range_value(score_impact(10000), score_impact(20000), n) * 100 / 8 +
        range_value(score_impact(20000), score_impact(30000), n) * 100 / 4 +
        range_value(score_impact(30000), score_impact(40000), n) * 100 / 2 +
        range_value(score_impact(40000), float('inf'), n) / 0.01
    )

def range_value(min_value, max_value, score):
    return max(min(score, max_value) - min_value, 0)