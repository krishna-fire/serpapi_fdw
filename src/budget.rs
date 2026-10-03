//! Account-wide credit budget persisted in the wrapper's metadata slot
//! (`wrappers_fdw_stats.metadata`, written by the host through `stats::set_metadata`).
//!
//! Counts every successful `/search` call as one credit (SerpApi's own cache hits are
//! free but indistinguishable in the response, so we over-count in the safe direction).
//! Archive replays and `/account.json` are not counted.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Default)]
pub struct Budget {
    /// `YYYYMMDDHH` in UTC
    pub hour_key: String,
    pub hour_used: u32,
    /// `YYYYMM` in UTC
    pub month_key: String,
    pub month_used: u32,
    /// epoch seconds of the last recorded search
    #[serde(default)]
    pub last_search_at: i64,
}

/// Howard Hinnant's civil-from-days; returns (year, month, day) in UTC.
pub fn civil_from_epoch(secs: i64) -> (i64, u32, u32) {
    let days = secs.div_euclid(86_400);
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

pub fn hour_key(secs: i64) -> String {
    let (y, m, d) = civil_from_epoch(secs);
    let h = secs.rem_euclid(86_400) / 3600;
    format!("{y:04}{m:02}{d:02}{h:02}")
}

pub fn month_key(secs: i64) -> String {
    let (y, m, _) = civil_from_epoch(secs);
    format!("{y:04}{m:02}")
}

/// Epoch seconds at which the current hour window ends.
pub fn next_hour_start(secs: i64) -> i64 {
    (secs.div_euclid(3600) + 1) * 3600
}

impl Budget {
    /// Load from the metadata string (if any) and roll windows forward to `now`.
    pub fn load(metadata: Option<&str>, now: i64) -> Budget {
        let mut b: Budget = metadata
            .and_then(|s| serde_json::from_str::<Budget>(s).ok())
            .unwrap_or_default();
        let hk = hour_key(now);
        let mk = month_key(now);
        if b.hour_key != hk {
            b.hour_key = hk;
            b.hour_used = 0;
        }
        if b.month_key != mk {
            b.month_key = mk;
            b.month_used = 0;
        }
        b
    }

    pub fn to_metadata(&self) -> String {
        serde_json::to_string(self).unwrap_or_else(|_| "{}".to_string())
    }

    /// Fail closed if either cap would be exceeded by `n` more searches.
    pub fn check(&self, n: u32, hourly_cap: u32, monthly_cap: u32, now: i64) -> Result<(), String> {
        if hourly_cap > 0 && self.hour_used + n > hourly_cap {
            return Err(format!(
                "serpapi: hourly cap reached ({}/{} searches this hour); resets in {} min. No request was sent. Raise hourly_cap on the server if your plan allows.",
                self.hour_used,
                hourly_cap,
                ((next_hour_start(now) - now).max(0) + 59) / 60
            ));
        }
        if monthly_cap > 0 && self.month_used + n > monthly_cap {
            return Err(format!(
                "serpapi: monthly cap reached ({}/{} searches in {}). No request was sent. Raise monthly_cap on the server if your plan allows, or use search_id replay (free).",
                self.month_used, monthly_cap, self.month_key
            ));
        }
        Ok(())
    }

    pub fn record(&mut self, now: i64) {
        self.hour_used += 1;
        self.month_used += 1;
        self.last_search_at = now;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn civil_dates() {
        assert_eq!(civil_from_epoch(0), (1970, 1, 1));
        // 2026-09-27 00:00:00 UTC = 1790467200
        assert_eq!(civil_from_epoch(1_790_467_200), (2026, 9, 27));
        assert_eq!(hour_key(1_790_467_200 + 3_601), "2026092701");
        assert_eq!(month_key(1_790_467_200), "202609");
    }

    #[test]
    fn windows_roll_and_caps_fail_closed() {
        let now = 1_790_467_200;
        let mut b = Budget::load(None, now);
        for _ in 0..50 {
            b.check(1, 50, 250, now).unwrap();
            b.record(now);
        }
        assert!(b.check(1, 50, 250, now).unwrap_err().contains("hourly cap"));
        // next hour: hourly resets, monthly continues
        let later = now + 3600;
        let b2 = Budget::load(Some(&b.to_metadata()), later);
        assert_eq!(b2.hour_used, 0);
        assert_eq!(b2.month_used, 50);
        // next month: both reset
        let b3 = Budget::load(Some(&b.to_metadata()), now + 40 * 86_400);
        assert_eq!(b3.month_used, 0);
    }

    #[test]
    fn corrupt_metadata_is_ignored() {
        let b = Budget::load(Some("not json"), 1_790_467_200);
        assert_eq!(b.hour_used, 0);
    }
}
