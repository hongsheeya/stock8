import datetime

KST = datetime.timezone(datetime.timedelta(hours=9))


class Time:
    def aware_now(self):
        return datetime.datetime.now(KST)

    def now(self):
        return self.aware_now().replace(tzinfo=None)

    def today(self, fmt="%Y-%m-%d"):
        return self.now().strftime(fmt)

    def compact_date(self):
        return self.now().strftime("%Y%m%d")

    def parse(self, value=None):
        if value in (None, ""):
            return None
        if isinstance(value, datetime.datetime):
            return value
        if isinstance(value, datetime.date):
            return datetime.datetime.combine(value, datetime.time.min)

        text = str(value or "").strip()
        if text == "":
            return None

        normalized = text
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            return datetime.datetime.fromisoformat(normalized)
        except Exception:
            pass

        for fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                return datetime.datetime.strptime(text[:26], fmt)
            except Exception:
                continue
        return None

    def to_kst(self, value=None, assume_naive_kst=True):
        dt = self.parse(value if value is not None else self.aware_now())
        if dt is None:
            return None
        if getattr(dt, "tzinfo", None) is None:
            if assume_naive_kst:
                return dt
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(KST).replace(tzinfo=None)

    def normalize(self, value=None, fmt="%Y-%m-%d %H:%M:%S", fallback=""):
        dt = self.to_kst(value)
        if dt is None:
            if value in (None, ""):
                return fallback
            return str(value)
        return dt.strftime(fmt)

    def isoformat(self, value=None, with_offset=False):
        if with_offset:
            dt = self.to_kst(value if value is not None else self.aware_now())
            if dt is None:
                return ""
            return dt.replace(tzinfo=KST).isoformat()
        dt = self.to_kst(value if value is not None else self.now())
        if dt is None:
            return ""
        return dt.isoformat()


Model = Time()
