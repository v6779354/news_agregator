from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import config
from services.collector import collect
from bot.telegram import scheduled_digest, poll

def start():
    scheduler = BackgroundScheduler(timezone=config.TIMEZONE, job_defaults={'max_instances':1, 'coalesce':True, 'misfire_grace_time':300})
    scheduler.add_job(collect, 'interval', minutes=config.COLLECT_MINUTES, next_run_time=datetime.now(), id='collect')
    scheduler.add_job(scheduled_digest, 'cron', hour=config.DIGEST_HOUR, minute=config.DIGEST_MINUTE, id='digest')
    scheduler.add_job(poll, 'interval', seconds=15, id='telegram')
    scheduler.start()
    return scheduler
