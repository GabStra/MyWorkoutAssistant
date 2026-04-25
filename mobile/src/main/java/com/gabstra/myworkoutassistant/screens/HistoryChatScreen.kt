package com.gabstra.myworkoutassistant.screens

import android.content.Context
import android.content.pm.ApplicationInfo
import android.util.Log
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.insights.ConfigurableWorkoutInsightsEngine
import com.gabstra.myworkoutassistant.insights.HistoryChatMessage
import com.gabstra.myworkoutassistant.insights.HistoryChatMessageRole
import com.gabstra.myworkoutassistant.insights.WorkoutHistoryChatPrepareResult
import com.gabstra.myworkoutassistant.insights.WorkoutInsightsRequest
import com.gabstra.myworkoutassistant.insights.WorkoutInsightsToolContext
import com.gabstra.myworkoutassistant.insights.buildHistoryChatUserPrompt
import com.gabstra.myworkoutassistant.insights.prepareExerciseHistoryChatContext
import com.gabstra.myworkoutassistant.insights.prepareWorkoutSessionHistoryChatContext
import com.gabstra.myworkoutassistant.insights.WorkoutInsightMarkdown
import com.gabstra.myworkoutassistant.insights.sanitizeInsightMarkdown
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.RestHistoryDao
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.UUID

/**
 * Debug logs for history chat LLM I/O. Filter: `adb logcat -s HistoryChatScreen`.
 * Only runs when the app is debuggable (typical `debug` install; not Play release).
 *
 * Each send uses an `id=` short UUID so request chunks and assistant output lines match in logcat.
 */
private object HistoryChatScreenLog {
    private const val TAG = "HistoryChatScreen"
    private const val CHUNK_SIZE = 3500

    private fun isDebuggable(appContext: Context): Boolean =
        (appContext.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0

    fun llmInteractionRequest(
        appContext: Context,
        interactionId: String,
        mode: HistoryChatScreenMode,
        request: WorkoutInsightsRequest,
    ) {
        if (!isDebuggable(appContext)) return
        val toolSummary = when (val tc = request.toolContext) {
            null -> "toolContext=null"
            is WorkoutInsightsToolContext.Exercise ->
                "tool=Exercise exerciseName=${tc.exerciseName} exportChars=${tc.markdown.length}"
            is WorkoutInsightsToolContext.WorkoutSession ->
                "tool=WorkoutSession workoutLabel=${tc.workoutLabel} exportChars=${tc.markdown.length}"
        }
        Log.d(
            TAG,
            "llm_request id=$interactionId mode=$mode requestTitle=${request.title} " +
                "systemChars=${request.systemPrompt.length} userChars=${request.prompt.length} " +
                "historyChatSystemIncludesData=${request.historyChatSystemIncludesData} " +
                "useTransportToolCalling=${request.useTransportToolCalling} $toolSummary",
        )
        if (request.customInstructions.isNotBlank()) {
            logChunked("llm_request_custom_instructions", interactionId, request.customInstructions)
        }
        logChunked("llm_request_system", interactionId, request.systemPrompt)
        logChunked("llm_request_user", interactionId, request.prompt)
    }

    fun llmInteractionFailure(appContext: Context, interactionId: String, e: Exception) {
        if (!isDebuggable(appContext)) return
        Log.e(TAG, "llm_failure id=$interactionId ${e.javaClass.simpleName}: ${e.message}", e)
    }

    fun assistantMarkdown(
        appContext: Context,
        interactionId: String,
        turn: String,
        mode: HistoryChatScreenMode,
        rawMarkdown: String,
    ) {
        if (!isDebuggable(appContext)) return
        val sanitized = sanitizeInsightMarkdown(rawMarkdown)
        Log.d(
            TAG,
            "assistant_markdown id=$interactionId turn=$turn mode=$mode rawLen=${rawMarkdown.length} " +
                "sanitizedLen=${sanitized.length}",
        )
        logChunked("assistant_markdown_raw", interactionId, rawMarkdown)
        logChunked("assistant_markdown_sanitized", interactionId, sanitized)
    }

    private fun logChunked(label: String, interactionId: String, text: String) {
        if (text.isEmpty()) {
            Log.d(TAG, "$label id=$interactionId <empty>")
            return
        }
        val totalParts = (text.length + CHUNK_SIZE - 1) / CHUNK_SIZE
        var start = 0
        var partIndex = 1
        while (start < text.length) {
            val end = (start + CHUNK_SIZE).coerceAtMost(text.length)
            Log.d(TAG, "$label id=$interactionId part $partIndex/$totalParts: ${text.substring(start, end)}")
            start = end
            partIndex++
        }
    }
}

sealed class HistoryChatScreenMode {
    data class Exercise(
        val workoutId: UUID,
        val exerciseId: UUID,
    ) : HistoryChatScreenMode()

    data class WorkoutSession(
        val workoutId: UUID,
        val workoutHistoryId: UUID,
    ) : HistoryChatScreenMode()
}

private sealed class HistoryChatPrepareUi {
    data object Loading : HistoryChatPrepareUi()
    data class Ready(
        val title: String,
        val requestBase: WorkoutInsightsRequest,
    ) : HistoryChatPrepareUi()

    data class Error(val message: String) : HistoryChatPrepareUi()
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HistoryChatScreen(
    mode: HistoryChatScreenMode,
    appViewModel: AppViewModel,
    workoutHistoryDao: WorkoutHistoryDao,
    workoutRecordDao: WorkoutRecordDao,
    setHistoryDao: SetHistoryDao,
    restHistoryDao: RestHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    onGoBack: () -> Unit,
) {
    val workouts by appViewModel.workoutsFlow.collectAsState()
    val workoutStore = appViewModel.workoutStore
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val insightsEngine = remember(context) {
        ConfigurableWorkoutInsightsEngine(context.applicationContext)
    }

    var prepareUi by remember(mode) { mutableStateOf<HistoryChatPrepareUi>(HistoryChatPrepareUi.Loading) }
    var messages by remember(mode) { mutableStateOf<List<HistoryChatMessage>>(emptyList()) }
    var composerText by remember(mode) { mutableStateOf("") }
    var sendError by remember(mode) { mutableStateOf<String?>(null) }
    var isSending by remember(mode) { mutableStateOf(false) }
    var generationJob by remember { mutableStateOf<Job?>(null) }

    LaunchedEffect(mode) {
        generationJob?.cancel()
        generationJob = null
    }

    DisposableEffect(Unit) {
        onDispose {
            generationJob?.cancel()
        }
    }

    LaunchedEffect(mode, workouts, workoutStore) {
        prepareUi = HistoryChatPrepareUi.Loading
        val result = withContext(Dispatchers.IO) {
            when (mode) {
                is HistoryChatScreenMode.Exercise -> {
                    val workout = workouts.find { it.id == mode.workoutId }
                        ?: return@withContext WorkoutHistoryChatPrepareResult.Failure("Workout not found.")
                    val exercise = appViewModel.getExerciseById(workout, mode.exerciseId)
                        ?: return@withContext WorkoutHistoryChatPrepareResult.Failure("Exercise not found.")
                    prepareExerciseHistoryChatContext(
                        exercise = exercise,
                        workoutHistoryDao = workoutHistoryDao,
                        setHistoryDao = setHistoryDao,
                        restHistoryDao = restHistoryDao,
                        exerciseSessionProgressionDao = exerciseSessionProgressionDao,
                        workouts = workouts,
                        workoutStore = workoutStore,
                    )
                }
                is HistoryChatScreenMode.WorkoutSession -> {
                    prepareWorkoutSessionHistoryChatContext(
                        workoutHistoryId = mode.workoutHistoryId,
                        workoutHistoryDao = workoutHistoryDao,
                        workoutRecordDao = workoutRecordDao,
                        setHistoryDao = setHistoryDao,
                        restHistoryDao = restHistoryDao,
                        exerciseSessionProgressionDao = exerciseSessionProgressionDao,
                        workoutStore = workoutStore,
                    )
                }
            }
        }
        prepareUi = when (result) {
            is WorkoutHistoryChatPrepareResult.Failure ->
                HistoryChatPrepareUi.Error(result.message)
            is WorkoutHistoryChatPrepareResult.Ready ->
                HistoryChatPrepareUi.Ready(
                    title = result.title,
                    requestBase = WorkoutInsightsRequest(
                        title = result.title,
                        prompt = "",
                        systemPrompt = result.systemPrompt,
                        toolContext = result.toolContext,
                        useTransportToolCalling = false,
                        historyChatSystemIncludesData = true,
                    ),
                )
        }
    }

    fun stopGeneration() {
        generationJob?.cancel()
        generationJob = null
    }

    fun submitCurrentUserTurn(ready: HistoryChatPrepareUi.Ready) {
        val trimmed = composerText.trim()
        if (trimmed.isBlank() || isSending) return
        sendError = null
        composerText = ""
        val userMessage = HistoryChatMessage(role = HistoryChatMessageRole.User, content = trimmed)
        val updatedThread = messages + userMessage
        messages = updatedThread
        isSending = true
        generationJob?.cancel()
        generationJob = scope.launch {
            val prior = updatedThread.dropLast(1)
            val prompt = buildHistoryChatUserPrompt(
                priorMessages = prior,
                currentUserContent = userMessage.content,
            )
            val request = ready.requestBase.copy(prompt = prompt)
            val interactionId = UUID.randomUUID().toString().take(8)
            HistoryChatScreenLog.llmInteractionRequest(
                appContext = context.applicationContext,
                interactionId = interactionId,
                mode = mode,
                request = request,
            )
            var lastText = ""
            try {
                insightsEngine.generateInsights(request).collect { chunk ->
                    lastText = chunk.text
                }
                val reply = lastText.ifBlank { "No reply was generated." }
                HistoryChatScreenLog.assistantMarkdown(
                    appContext = context.applicationContext,
                    interactionId = interactionId,
                    turn = "complete",
                    mode = mode,
                    rawMarkdown = reply,
                )
                messages = messages + HistoryChatMessage(role = HistoryChatMessageRole.Assistant, content = reply)
            } catch (e: CancellationException) {
                val partial = lastText.trim()
                val stoppedContent = if (partial.isNotBlank()) {
                    "$partial\n\n_(Stopped.)_"
                } else {
                    "_(Stopped.)_"
                }
                HistoryChatScreenLog.assistantMarkdown(
                    appContext = context.applicationContext,
                    interactionId = interactionId,
                    turn = "stopped",
                    mode = mode,
                    rawMarkdown = stoppedContent,
                )
                messages = messages + HistoryChatMessage(
                    role = HistoryChatMessageRole.Assistant,
                    content = stoppedContent,
                )
                throw e
            } catch (e: Exception) {
                HistoryChatScreenLog.llmInteractionFailure(
                    appContext = context.applicationContext,
                    interactionId = interactionId,
                    e = e,
                )
                sendError = e.message ?: "Unable to generate a reply."
            } finally {
                isSending = false
                generationJob = null
            }
        }
    }

    Scaffold(
        modifier = Modifier.imePadding(),
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                    titleContentColor = MaterialTheme.colorScheme.onBackground,
                    navigationIconContentColor = MaterialTheme.colorScheme.onBackground,
                ),
                title = {
                    Text(
                        text = when (val p = prepareUi) {
                            is HistoryChatPrepareUi.Ready -> p.title
                            else -> "History chat"
                        },
                        style = MaterialTheme.typography.titleLarge,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onGoBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { padding ->
        when (val p = prepareUi) {
            HistoryChatPrepareUi.Loading -> {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(padding),
                    contentAlignment = Alignment.Center,
                ) {
                    CircularProgressIndicator()
                }
            }
            is HistoryChatPrepareUi.Error -> {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(padding)
                        .padding(24.dp),
                    verticalArrangement = Arrangement.Center,
                ) {
                    Text(text = p.message, style = MaterialTheme.typography.bodyLarge)
                    TextButton(onClick = onGoBack, modifier = Modifier.padding(top = 16.dp)) {
                        Text("Go back")
                    }
                }
            }
            is HistoryChatPrepareUi.Ready -> {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(padding),
                ) {
                    LazyColumn(
                        modifier = Modifier
                            .weight(1f)
                            .fillMaxWidth(),
                        contentPadding = PaddingValues(16.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        items(messages, key = { it.id }) { message ->
                            HistoryChatBubble(message = message)
                        }
                    }
                    if (isSending) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            LinearProgressIndicator(modifier = Modifier.weight(1f))
                            TextButton(onClick = { stopGeneration() }) {
                                Icon(
                                    Icons.Default.Stop,
                                    contentDescription = "Stop generating",
                                    modifier = Modifier.padding(end = 4.dp),
                                )
                                Text("Stop")
                            }
                        }
                    }
                    sendError?.let { err ->
                        Text(
                            text = err,
                            color = MaterialTheme.colorScheme.error,
                            style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                        )
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 8.dp),
                            horizontalArrangement = Arrangement.End,
                        ) {
                            TextButton(
                                onClick = {
                                    sendError = null
                                    if (messages.lastOrNull()?.role == HistoryChatMessageRole.User) {
                                        submitCurrentUserTurn(p)
                                    }
                                },
                                enabled = !isSending && messages.lastOrNull()?.role == HistoryChatMessageRole.User,
                            ) {
                                Text("Retry")
                            }
                        }
                    }
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(8.dp),
                        verticalAlignment = Alignment.Bottom,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        OutlinedTextField(
                            value = composerText,
                            onValueChange = { composerText = it },
                            modifier = Modifier.weight(1f),
                            enabled = !isSending,
                            placeholder = { Text("Ask about this history…") },
                            minLines = 1,
                            maxLines = 5,
                        )
                        IconButton(
                            onClick = { submitCurrentUserTurn(p) },
                            enabled = !isSending && composerText.isNotBlank(),
                        ) {
                            Icon(Icons.Default.Send, contentDescription = "Send")
                        }
                    }
                }
            }
        }
    }
}

private val HistoryChatTurnShape = RoundedCornerShape(12.dp)

@Composable
private fun HistoryChatBubble(
    message: HistoryChatMessage,
) {
    val isUser = message.role == HistoryChatMessageRole.User
    val scheme = MaterialTheme.colorScheme
    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = if (isUser) Alignment.End else Alignment.Start,
    ) {
        Text(
            text = if (isUser) "You" else "Assistant",
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.Medium,
            color = scheme.primary,
            modifier = Modifier.padding(bottom = 6.dp, start = 2.dp, end = 2.dp),
        )
        val bubbleColor = scheme.surfaceContainerHighest.copy(alpha = 0.55f)
        Surface(
            modifier = Modifier.fillMaxWidth(0.92f),
            shape = HistoryChatTurnShape,
            color = bubbleColor,
            border = BorderStroke(
                width = 1.dp,
                color = scheme.outline.copy(alpha = 0.55f),
            ),
        ) {
            Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp)) {
                if (isUser) {
                    Text(
                        text = message.content,
                        style = MaterialTheme.typography.bodyLarge,
                        color = scheme.onSurface,
                    )
                } else {
                    WorkoutInsightMarkdown(
                        markdown = message.content,
                        modifier = Modifier.fillMaxWidth(),
                        baseTypographyStyle = MaterialTheme.typography.bodyLarge,
                    )
                }
            }
        }
    }
}
