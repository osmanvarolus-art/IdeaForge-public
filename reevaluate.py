#!/usr/bin/env python3
"""Re-evaluate specific ideas with new evaluation prompt (eval_version=2)"""
import sqlite3
import sys
import time

DB_PATH = "ideaforge.db"
IDEA_IDS = [3, 6, 7, 8, 11, 15, 16, 21, 28, 30]

def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    print(f"Re-evaluating {len(IDEA_IDS)} ideas with new prompt...")

    for idea_id in IDEA_IDS:
        # Reset evaluation status to trigger re-evaluation
        c.execute("""
            UPDATE ideas
            SET eval_status='pending',
                eval_verdict=NULL,
                eval_fit_score=NULL,
                eval_complexity=NULL,
                eval_one_sentence=NULL,
                eval_version=2,
                updated_at=datetime('now')
            WHERE id=?
        """, (idea_id,))
        print(f"  Queued idea {idea_id} for re-evaluation")

    conn.commit()
    conn.close()

    print("\nWaiting for evaluations to complete (60s)...")
    time.sleep(60)

    # Check results
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, video_title, eval_verdict, eval_fit_score, eval_complexity, eval_version
        FROM ideas
        WHERE id IN ({})
        ORDER BY eval_verdict, eval_fit_score DESC
    """.format(','.join('?' * len(IDEA_IDS))), IDEA_IDS)

    results = c.fetchall()

    print("\n" + "="*80)
    print("RE-EVALUATION RESULTS (eval_version=2)")
    print("="*80)

    verdict_counts = {'BUILD': 0, 'PARK': 0, 'SKIP': 0}
    for row in results:
        idea_id, title, verdict, fit_score, complexity, version = row
        if verdict:
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
        title_short = (title[:60] + '...') if len(title) > 60 else title
        print(f"{idea_id:3d} | {verdict:5s} | {fit_score:3d} | {complexity} | {title_short}")

    print("\nVERDICT DISTRIBUTION:")
    total = sum(verdict_counts.values())
    for v, count in verdict_counts.items():
        pct = (count/total*100) if total > 0 else 0
        print(f"  {v:5s}: {count:2d} ({pct:5.1f}%)")

    conn.close()

if __name__ == '__main__':
    main()
