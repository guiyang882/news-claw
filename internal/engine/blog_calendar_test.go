package engine

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestBlogCalendarUsesFridayAndSundayEvenings(t *testing.T) {
	loc, _ := time.LoadLocation("Asia/Shanghai")
	for _, id := range []string{"daily-blog-agy-codex", "daily-blog-readiness", "daily-blog-watchdog", "daily-blog-delivery-audit"} {
		raw, err := os.ReadFile(filepath.Join("../../config/tasks", id+".json"))
		if err != nil {
			t.Fatal(err)
		}
		var definition struct {
			Schedule string `json:"schedule"`
			Timezone string `json:"timezone"`
		}
		var config Config
		if err := json.Unmarshal(raw, &definition); err != nil {
			t.Fatal(err)
		}
		if err := json.Unmarshal(raw, &config); err != nil {
			t.Fatal(err)
		}
		task := Task{Schedule: definition.Schedule, Timezone: definition.Timezone, Config: config}
		calendar, _, err := task.Calendar()
		if err != nil {
			t.Fatal(err)
		}
		cursor := time.Date(2026, 10, 27, 0, 0, 0, 0, loc)
		end := cursor.AddDate(0, 0, 14)
		days := map[string]bool{}
		for next := calendar.Next(cursor); next.Before(end); next = calendar.Next(next) {
			local := next.In(loc)
			if local.Weekday() != time.Friday && local.Weekday() != time.Sunday || local.Hour() < 19 {
				t.Fatalf("%s unexpected slot: %s", id, local)
			}
			days[local.Format("2006-01-02")] = true
		}
		if len(days) != 4 {
			t.Fatalf("%s: expected 4 edition days over two weeks, got %v", id, days)
		}
	}
}
