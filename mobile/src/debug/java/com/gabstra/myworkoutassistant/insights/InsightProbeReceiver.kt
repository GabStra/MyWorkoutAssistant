package com.gabstra.myworkoutassistant.insights

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import com.gabstra.myworkoutassistant.shared.export.WorkoutSessionMarkdownResult
import com.gabstra.myworkoutassistant.shared.export.buildWorkoutSessionMarkdown
import kotlinx.coroutines.runBlocking

/** The rule the X-bisect localized the degenerate "." response to (chars 600-700). */
private const val SUSPECT_RULE =
    "- Preserve the direction of explicit evidence: if the data says zero, none, no previous, " +
        "disabled, stopped, incomplete, missed, or below target, do not rewrite it as a " +
        "positive or completed outcome"

/**
 * Debug-only controlled experiment harness for the on-device tool-calling path.
 * Drive with:
 *   adb shell am broadcast -a com.gabstra.myworkoutassistant.DEBUG_INSIGHT_PROBE --es variant A
 * Runs as a foreground service (a plain receiver hits the 60s broadcast ANR).
 * Variants isolate one request-shape variable at a time; results land in logcat
 * under "InsightProbe".
 */
class InsightProbeReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val variant = intent.getStringExtra("variant")?.uppercase() ?: "A"
        context.startForegroundService(
            Intent(context, InsightProbeService::class.java)
                .putExtra("variant", variant)
                .putExtra("len", intent.getIntExtra("len", 0))
                .putExtra("rule", intent.getStringExtra("rule") ?: "")
        )
    }
}

class InsightProbeService : Service() {

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val channel = NotificationChannel("insight_probe", "Insight probe", NotificationManager.IMPORTANCE_LOW)
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        val notification = Notification.Builder(this, "insight_probe")
            .setContentTitle("Insight probe running")
            .setSmallIcon(android.R.drawable.ic_menu_compass)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(1, notification)
        }

        val variant = intent?.getStringExtra("variant")?.uppercase() ?: "A"
        val len = intent?.getIntExtra("len", 0) ?: 0
        val ruleText = intent?.getStringExtra("rule") ?: ""
        Thread {
            try {
                runProbe(applicationContext, variant, len, ruleText)
            } catch (t: Throwable) {
                Log.e("InsightProbe", "variant=$variant crashed", t)
            } finally {
                stopSelf(startId)
            }
        }.start()
        return START_NOT_STICKY
    }

    private fun runProbe(context: Context, variant: String, extraLen: Int = 0, ruleText: String = "") {
        val engine = ConfigurableWorkoutInsightsEngine(context)
        val longSystem = buildToolEnabledSystemPrompt(WORKOUT_INSIGHTS_SYSTEM_PROMPT)
        val shortSystem = buildToolEnabledSystemPrompt(
            "You are a workout insights assistant. Explain the session concisely."
        )
        val longUser = buildWorkoutSessionToolCallingPrompt(
            workoutLabel = "Cyclette - LISS (Workout category: Biking stationary)",
            sessionStatusSummary = "completed normally.",
        )
        val shortUser = "Summarize how this session went."

        val toolContext = WorkoutInsightsToolContext.Exercise(
            title = "probe",
            exerciseName = "Probe Squat",
            markdown = """
                # Probe Squat history
                ## S3: 2026-10-08
                - Exec: 3x8 @ 100 kg
                ## S2: 2026-10-05
                - Exec: 3x8 @ 97.5 kg
                ## S1: 2026-10-01
                - Exec: 3x7 @ 95 kg
            """.trimIndent(),
        )

        val (systemPrompt, userPrompt, conversation) = when (variant) {
            "A" -> Triple(shortSystem, shortUser, emptyList<HistoryChatMessage>())
            // Isolate system-prompt length (real 6.7K insight system prompt).
            "B" -> Triple(longSystem, shortUser, emptyList())
            // Isolate user-prompt length (real 2K task block).
            "C" -> Triple(shortSystem, longUser, emptyList())
            // Real failing combo but forced onto the 384 chat cap via a seeded conversation.
            "D" -> Triple(
                longSystem,
                longUser,
                listOf(HistoryChatMessage(role = HistoryChatMessageRole.User, content = longUser)),
            )
            // Exact failing combo reproduced from the on-device dumps.
            "E" -> Triple(longSystem, longUser, emptyList())
            // Neutral filler padded to the same size as the real system prompt:
            // fails => size limit, works => prompt content trigger.
            "F" -> Triple(
                shortSystem + "\n\n" + "Coaching notes: keep advice grounded, concise, and safe. ".repeat(
                    (6_672 - shortSystem.length) / 62,
                ),
                shortUser,
                emptyList(),
            )
            // Real system prompt truncated to ~3K chars.
            "G" -> Triple(longSystem.take(3_000), shortUser, emptyList())
            // Real system prompt truncated to ~4.5K chars.
            "H" -> Triple(longSystem.take(4_500), shortUser, emptyList())
            // Real system prompt truncated to an arbitrary length from the "len" extra.
            "X" -> Triple(
                longSystem.take(if (extraLen > 0) extraLen else 1_500),
                shortUser,
                emptyList(),
            )
            // Dump the REAL session markdown for the newest done history of the
            // Cyclette workout (no LLM call) to inspect evidence structure.
            "M" -> {
                val db = com.gabstra.myworkoutassistant.shared.AppDatabase.getDatabase(context)
                val repo = com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository(context.filesDir)
                val workoutStore = repo.getWorkoutStore()
                val md = runBlocking {
                    val hid = db.workoutHistoryDao().getLatestWorkoutHistoryByWorkoutId(
                        java.util.UUID.fromString("ab3db22c-6a5b-47f0-b813-5228fad5b956")
                    )
                    if (hid == null) {
                        null
                    } else {
                        buildWorkoutSessionMarkdown(
                            workoutHistoryId = hid.id,
                            workoutHistoryDao = db.workoutHistoryDao(),
                            setHistoryDao = db.setHistoryDao(),
                            restHistoryDao = db.restHistoryDao(),
                            exerciseSessionProgressionDao = db.exerciseSessionProgressionDao(),
                            workoutStore = workoutStore,
                        )
                    }
                }
                when (md) {
                    null -> Log.w("InsightProbe", "variant=M no history found")
                    is WorkoutSessionMarkdownResult.Success ->
                        Log.i("InsightProbe", "variant=M BODY chars=" + md.markdown.length + "\n" + md.markdown)
                    else -> Log.w("InsightProbe", "variant=M failed")
                }
                return
            }
            // Dump the COMPACT markdown + overview lines for the same session.
            "M2" -> {
                val db = com.gabstra.myworkoutassistant.shared.AppDatabase.getDatabase(context)
                val repo = com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository(context.filesDir)
                val workoutStore = repo.getWorkoutStore()
                val result = runBlocking {
                    val hid = db.workoutHistoryDao().getLatestWorkoutHistoryByWorkoutId(
                        java.util.UUID.fromString("ab3db22c-6a5b-47f0-b813-5228fad5b956")
                    )
                    hid
                }
                if (result == null) {
                    Log.w("InsightProbe", "variant=M2 no history")
                    return
                }
                val raw = runBlocking {
                    buildWorkoutSessionMarkdown(
                        workoutHistoryId = result.id,
                        workoutHistoryDao = db.workoutHistoryDao(),
                        setHistoryDao = db.setHistoryDao(),
                        restHistoryDao = db.restHistoryDao(),
                        exerciseSessionProgressionDao = db.exerciseSessionProgressionDao(),
                        workoutStore = workoutStore,
                    )
                }
                val compact = (raw as? WorkoutSessionMarkdownResult.Success)?.let {
                    compactWorkoutSessionMarkdown(it.markdown)
                }
                if (compact == null) {
                    Log.w("InsightProbe", "variant=M2 failed")
                    return
                }
                val (top, sections) = splitWorkoutSessionOverviewAndSections(compact)
                Log.i("InsightProbe", "variant=M2 sections=" + sections.keys)
                sections.forEach { (title, block) ->
                    Log.i("InsightProbe", "variant=M2 OVERVIEW[" + title + "]=" + buildWorkoutSectionOverviewLine(block))
                }
                Log.i("InsightProbe", "variant=M2 COMPACT\n" + compact)
                return
            }
            // Short system + the one suspect rule, isolating the content trigger.
            "Y" -> Triple(
                shortSystem + "\n\n" + SUSPECT_RULE,
                shortUser,
                emptyList(),
            )
            // Suspect rule split in halves: extra 1 = first half, 2 = second half.
            "Z" -> Triple(
                shortSystem + "\n\n" + if (extraLen == 2) {
                    SUSPECT_RULE.substring(SUSPECT_RULE.length / 2)
                } else {
                    SUSPECT_RULE.take(SUSPECT_RULE.length / 2)
                },
                shortUser,
                emptyList(),
            )
            // Task + neutral padding to the exact same total length as the real prompt.
            "S4" -> Triple(
                buildToolEnabledSystemPrompt(WORKOUT_INSIGHTS_TOOL_SYSTEM_PROMPT),
                REAL_USER_PROMPT.substringBefore("Precomputed session facts") +
                    "Reference context follows. ".repeat(70),
                emptyList(),
            )
            // Real facts block but with em-dashes and special characters normalized.
            "S5" -> Triple(
                buildToolEnabledSystemPrompt(WORKOUT_INSIGHTS_TOOL_SYSTEM_PROMPT),
                REAL_USER_PROMPT.replace("—", "-").replace("≤", "at or under"),
                emptyList(),
            )
            // FIX CANDIDATE: facts moved from user prompt into the system prompt
            // (the shape the history chat already uses successfully).
            "S6" -> Triple(
                withAlwaysAvailableFacts(
                    buildToolEnabledSystemPrompt(WORKOUT_INSIGHTS_TOOL_SYSTEM_PROMPT),
                    REAL_USER_PROMPT.substringAfter("Precomputed session facts (computed by the app from the recorded data; authoritative):"),
                ),
                REAL_USER_PROMPT.substringBefore("Precomputed session facts"),
                emptyList(),
            )
            // Exact real on-device request captured from the 16:54 dump (compact system
            // + task + facts) that returned " minutes".
            "S" -> Triple(
                buildToolEnabledSystemPrompt(WORKOUT_INSIGHTS_TOOL_SYSTEM_PROMPT),
                REAL_USER_PROMPT,
                emptyList(),
            )
            // Same as S with a short appended nudge (length-perturbation escape test).
            "S2" -> Triple(
                buildToolEnabledSystemPrompt(WORKOUT_INSIGHTS_TOOL_SYSTEM_PROMPT),
                REAL_USER_PROMPT + "\nAnswer thoroughly now.",
                emptyList(),
            )
            // Same as S with a slightly longer nudge.
            "S3" -> Triple(
                buildToolEnabledSystemPrompt(WORKOUT_INSIGHTS_TOOL_SYSTEM_PROMPT),
                REAL_USER_PROMPT + "\nStart with the overview tool, then write the full report.",
                emptyList(),
            )
            // Exact production insight shape: compact system + long real user prompt.
            "R" -> Triple(
                buildToolEnabledSystemPrompt(WORKOUT_INSIGHTS_TOOL_SYSTEM_PROMPT),
                longUser,
                emptyList(),
            )
            // The actual production compact tool-path system prompts.
            "P" -> Triple(
                buildToolEnabledSystemPrompt(if (extraLen == 2) EXERCISE_INSIGHTS_TOOL_SYSTEM_PROMPT else WORKOUT_INSIGHTS_TOOL_SYSTEM_PROMPT),
                if (extraLen == 2) "Summarize this exercise's latest session." else shortUser,
                emptyList(),
            )
            // Arbitrary rule text supplied via the "rule" string extra.
            "W" -> Triple(
                shortSystem + "\n\n" + ruleText,
                shortUser,
                emptyList(),
            )
            else -> {
                Log.w("InsightProbe", "unknown variant $variant")
                return
            }
        }

        val request = WorkoutInsightsRequest(
            title = "probe-$variant",
            prompt = userPrompt,
            systemPrompt = systemPrompt,
            toolContext = toolContext,
            useTransportToolCalling = true,
            conversationMessages = conversation,
        )

        Log.i(
            "InsightProbe",
            "variant=$variant len=$extraLen ruleChars=${ruleText.length} start systemChars=${systemPrompt.length} userChars=${userPrompt.length} " +
                "conversation=${conversation.size}",
        )
        val reply = runBlocking {
            val sb = StringBuilder()
            engine.generateInsights(request).collect { chunk -> sb.append(chunk.text) }
            sb.toString()
        }
        Log.i(
            "InsightProbe",
            "variant=$variant DONE replyChars=${reply.length} replyHead=" +
                reply.replace('\n', ' ').take(120),
        )
    }
}

/** The exact real insight user prompt (task + facts) captured from the on-device 16:54 dump. */
private const val REAL_USER_PROMPT = "Task: analyze the workout session \"Cyclette - LISS (Workout category: Biking stationary)\" and produce focused coaching insights.\nSession status: completed normally.\n\nWorkflow:\n1. Fetch the compact session overview first.\n2. Treat that overview as a first pass only; if it is mixed, incomplete, truncated, generic, or missing one of the main exercises, fetch specific sections before concluding.\n3. Use summary tools only when the remaining context is too large.\n4. If the session was not completed normally, treat that as an important constraint on interpretation.\n5. For lifting-dominant sessions, do not use modest session HR or 0% high-intensity exposure as the main risk by itself.\n6. Before writing final synthesis, verify the clearest lagging or improving exercise with a narrower retrieval when available.\n7. When a trend claim depends on previous sessions of this workout, retrieve them with get_previous_sessions instead of assuming.\n8. Stop tool use and write the final answer once you can explain what went well, what drifted, and any important constraint.\n\nPrecomputed session facts (computed by the app from the recorded data; authoritative):\nFACT Session duration: 55:09 (55 minutes)\nFACT Average heart rate: 140 bpm; peak 154 bpm\nFACT Heart-rate drift: the second half averaged -2 bpm versus the first half\nFACT 80% of HR samples stayed inside the 60-70% target zone\nFACT Session duration versus recent sessions of this workout: 55 minutes versus 55 minutes typical\nFACT Trend over the last 3 sessions of this workout: regressing — average HR is 6 bpm above the recent 133 bpm average; at a similar duration, a lower average HR means better aerobic efficiency\nFACT HR drift this session: -2 bpm versus your typical -2 bpm on this workout\nFACT Previous-session target check: the target was average HR at or under 131 bpm for about 55 minutes; this session averaged 140 bpm across 55 minutes — target not met\nFACT Next-session target: average heart rate at or under 140 bpm for about 55 minutes"
