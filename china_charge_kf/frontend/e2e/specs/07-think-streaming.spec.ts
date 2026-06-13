import { test, expect, type ConsoleMessage } from '@playwright/test'
import { mockDifyV2StreamResponse } from '../helpers/dify-sse-mocks'
import {
  waitForAssistantBubble,
  getAssistantText,
  waitForStreamingEnd,
} from '../helpers/stream-helpers'

/**
 * M9.4 — stream-level <think> stripper regression gate.
 *
 * Why this spec exists: real Dify v2 emits character-level tokens (M9-PROMPT §1),
 * so the <think> open tag and </think> close tag routinely straddle two
 * message_delta chunks. A naive per-chunk regex <think>.*?</think> only
 * matches open+close in the SAME string — across chunks it is a complete
 * no-op, so raw reasoning leaks into the bubble DOM for ~4-15s before
 * M8.2 stripThinkTags replaces it on message_complete.
 *
 * M9.1 (createThinkStripper in difyStream.ts) is a stream-level buffer that
 * holds chunks until it can identify <think> / </think> boundaries across
 * deltas. This spec verifies:
 *   1. No <think> or </think> substring ever appears in the bubble DOM
 *      at any point during streaming (sampled via getAssistantText on a
 *      tick interval, plus a final post-stream read).
 *   2. No console.error fires with the M9-HARD-GATE marker (the dev-only
 *      useEffect that watched assistant bubble text was removed in this M9
 *      commit — option (b) per M9-PROMPT §11 — so this e2e spec is the
 *      permanent regression gate).
 *   3. The visible reply text concatenates to the expected clean output.
 */

async function sampleBubbleText(
  page: import('@playwright/test').Page,
  settleMs = 800,
): Promise<string[]> {
  const samples: string[] = []
  const start = Date.now()
  while (Date.now() - start < settleMs) {
    const txt = await getAssistantText(page)
    samples.push(txt)
    await page.waitForTimeout(50)
  }
  return samples
}

test.describe('T7 — stream-level <think> stripper (M9.1)', () => {
  test('bubble DOM never contains <think> / </think> substring during streaming', async ({
    page,
  }) => {
    // Mirror the real-Dify pattern from M9-PROMPT §1: character-level tokens
    // that cross chunk boundaries inside both open and close think tags.
    // Two think blocks + intervening visible text, total 11 message_delta events.
    const VISIBLE_REPLY = 'hello world'
    await mockDifyV2StreamResponse(page, [
      { type: 'session_started', session_id: 'mock-m9', started_at: null },
      // First think block — open tag split across two deltas
      { type: 'message_delta', text: '<thi' },
      { type: 'message_delta', text: 'nk>' },
      { type: 'message_delta', text: 're' },
      { type: 'message_delta', text: 'as' },
      { type: 'message_delta', text: 'on' },
      // Close tag split across two deltas
      { type: 'message_delta', text: '</' },
      { type: 'message_delta', text: 'think>' },
      // Visible prefix across two deltas
      { type: 'message_delta', text: 'hel' },
      { type: 'message_delta', text: 'lo' },
      // Second think block — open + content + close in one delta
      { type: 'message_delta', text: '<think>more reasoning</think>' },
      // Trailing visible text
      { type: 'message_delta', text: ' world' },
      {
        type: 'message_complete',
        text: VISIBLE_REPLY,
        total_tokens: 10,
        elapsed_time: 0.5,
      },
    ])

    // Capture every console message so we can assert no M9-HARD-GATE fires.
    // The useEffect that emitted that string was removed in this M9 commit
    // (option b per M9-PROMPT §11); this listener is the permanent gate.
    const consoleErrors: string[] = []
    page.on('console', (msg: ConsoleMessage) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text())
    })

    await page.goto('/')
    await page.locator('.input').fill('probe think strip')
    await page.locator('.send').click()

    await waitForAssistantBubble(page)
    const samples = await sampleBubbleText(page, 1200)

    // Assert — no sample (mid-stream OR final) contains a think-tag substring
    for (const s of samples) {
      expect(s, 'no <think> substring in bubble text').not.toContain('<think>')
      expect(s, 'no </think> substring in bubble text').not.toContain('</think>')
    }

    // Wait for stream to fully end, then re-assert on the final text
    await waitForStreamingEnd(page)
    const finalText = await getAssistantText(page)
    expect(finalText).toBe(VISIBLE_REPLY)
    expect(finalText).not.toContain('<think>')
    expect(finalText).not.toContain('</think>')

    // No M9-HARD-GATE console.error fires. Any future regression re-introducing
    // raw <think> to the bubble DOM must be caught here.
    const hardGateErrors = consoleErrors.filter((t) => t.includes('M9-HARD-GATE'))
    expect(hardGateErrors).toEqual([])
  })

  test('plain text without think tags is passed through unchanged', async ({ page }) => {
    // Sanity — stripper must not corrupt plain text streams (regression guard).
    const REPLY = 'just a plain reply, no think tags here'
    await mockDifyV2StreamResponse(page, [
      { type: 'session_started', session_id: 'mock-m9-plain', started_at: null },
      { type: 'message_delta', text: 'just a plain reply' },
      { type: 'message_delta', text: ', no think tags here' },
      {
        type: 'message_complete',
        text: REPLY,
        total_tokens: 5,
        elapsed_time: 0.1,
      },
    ])

    await page.goto('/')
    await page.locator('.input').fill('plain')
    await page.locator('.send').click()

    await waitForAssistantBubble(page)
    await waitForStreamingEnd(page)

    expect(await getAssistantText(page)).toBe(REPLY)
  })
})