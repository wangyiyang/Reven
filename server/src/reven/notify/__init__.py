"""定时主动推送通用能力：调度（scheduler）/ 投递（notifier）/ 幂等（notification_log）三层。

首个挂载场景为 CRM 待跟进每日提醒（reven.crm.follow_up_reminder）；
后续 RSS 任务失败告警、系统巡检等场景按 DailyPushScene 协议接入即可。
"""
