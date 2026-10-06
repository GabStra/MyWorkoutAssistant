package com.gabstra.myworkoutassistant.screens

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.widget.Toast
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.composables.BreadcrumbScaffold
import com.gabstra.myworkoutassistant.shared.datalayer.MotionCaptureSyncDao
import com.gabstra.myworkoutassistant.shared.datalayer.MotionCaptureSyncMappings
import com.gabstra.myworkoutassistant.shared.datalayer.SensorSessionPayloadCodec
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionDao
import com.gabstra.myworkoutassistant.ui.theme.tertiaryContent
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.UUID

private val SessionTimestampFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")

private fun formatEpochMs(epochMs: Long): String =
    SessionTimestampFormatter.format(Instant.ofEpochMilli(epochMs).atZone(ZoneId.systemDefault()))

private fun formatSessionDuration(startedAtEpochMs: Long, endedAtEpochMs: Long?): String {
    if (endedAtEpochMs == null || endedAtEpochMs < startedAtEpochMs) return "Unfinished"
    val totalSeconds = (endedAtEpochMs - startedAtEpochMs) / 1000
    return "%d:%02d min".format(totalSeconds / 60, totalSeconds % 60)
}

/**
 * Zips the captured session directory into the app's external files directory so the user can
 * pull it off the device. Returns the written file, or null when the session directory is absent.
 * The project has no FileProvider configured, so the zip path is surfaced to the user instead of
 * being handed to the system share sheet.
 */
internal suspend fun zipSessionDirectoryForExport(
    context: Context,
    sessionDirectoryName: String
): File? = withContext(Dispatchers.IO) {
    val sessionDirectory = File(File(context.filesDir, "motion_capture/sessions"), sessionDirectoryName)
    if (!sessionDirectory.isDirectory) return@withContext null
    val exportRoot = File(context.getExternalFilesDir(null), "sensor_session_exports")
    exportRoot.mkdirs()
    val target = File(exportRoot, "$sessionDirectoryName.zip")
    val tempFile = File(exportRoot, "${target.name}.tmp")
    try {
        tempFile.outputStream().use { output ->
            output.write(SensorSessionPayloadCodec.zipDirectory(sessionDirectory))
        }
        if (!tempFile.renameTo(target)) {
            null
        } else {
            target
        }
    } catch (exception: Exception) {
        tempFile.delete()
        null
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SensorSessionsScreen(
    syncDao: MotionCaptureSyncDao,
    onBack: () -> Unit,
    onOpenSession: (UUID) -> Unit
) {
    val sessions by syncDao.observeAllSessions().collectAsState(initial = emptyList())
    val segmentCounts by syncDao.observeSegmentCounts().collectAsState(initial = emptyList())
    val segmentCountBySession = remember(segmentCounts) {
        segmentCounts.associate { it.sessionId to it.segmentCount }
    }

    BreadcrumbScaffold(
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Color.Transparent,
                    navigationIconContentColor = MaterialTheme.colorScheme.onBackground,
                    actionIconContentColor = MaterialTheme.colorScheme.onBackground
                ),
                title = {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .basicMarquee(iterations = Int.MAX_VALUE),
                        textAlign = TextAlign.Center,
                        text = "Sensor sessions (${sessions.size})"
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back"
                        )
                    }
                }
            )
        }
    ) { paddingValues ->
        if (sessions.isEmpty()) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues)
                    .padding(top = 12.dp),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = "No sensor sessions received from the watch yet",
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.tertiaryContent
                )
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues)
                    .padding(top = 12.dp)
                    .padding(horizontal = 16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(sessions, key = { it.id }) { session ->
                    SensorSessionCard(
                        session = session,
                        segmentCount = segmentCountBySession[session.id] ?: 0,
                        onClick = { onOpenSession(session.id) }
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SensorSessionCard(
    session: com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionEntity,
    segmentCount: Int,
    onClick: () -> Unit
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        onClick = onClick,
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text(
                text = formatEpochMs(session.startedAtEpochMs),
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurface
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = "${session.deviceManufacturer} ${session.deviceModel}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.tertiaryContent
            )
            Spacer(modifier = Modifier.height(4.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = formatSessionDuration(session.startedAtEpochMs, session.endedAtEpochMs),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(
                    text = "$segmentCount segments",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(
                    text = session.status,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.tertiaryContent
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SensorSessionDetailScreen(
    sessionId: UUID,
    sessionDao: MotionCaptureSessionDao,
    syncDao: MotionCaptureSyncDao,
    onBack: () -> Unit
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val session by produceState<com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionEntity?>(
        initialValue = null,
        key1 = sessionId
    ) {
        value = sessionDao.getById(sessionId)
    }
    val segments by syncDao.observeSegmentsBySessionId(sessionId).collectAsState(initial = emptyList())
    var exportedZipPath by remember { mutableStateOf<String?>(null) }
    var isExporting by remember { mutableStateOf(false) }

    BreadcrumbScaffold(
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Color.Transparent,
                    navigationIconContentColor = MaterialTheme.colorScheme.onBackground,
                    actionIconContentColor = MaterialTheme.colorScheme.onBackground
                ),
                title = {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .basicMarquee(iterations = Int.MAX_VALUE),
                        textAlign = TextAlign.Center,
                        text = "Sensor session"
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back"
                        )
                    }
                },
                actions = {
                    IconButton(
                        enabled = session != null && !isExporting,
                        onClick = {
                            val currentSession = session ?: return@IconButton
                            isExporting = true
                            scope.launch {
                                val exportedFile = zipSessionDirectoryForExport(
                                    context = context,
                                    sessionDirectoryName = currentSession.sessionDirectoryName
                                )
                                isExporting = false
                                if (exportedFile == null) {
                                    Toast.makeText(
                                        context,
                                        "Sensor session files are not on this phone.",
                                        Toast.LENGTH_SHORT
                                    ).show()
                                } else {
                                    exportedZipPath = exportedFile.absolutePath
                                }
                            }
                        }
                    ) {
                        Icon(
                            imageVector = Icons.Default.Share,
                            contentDescription = "Export session as zip"
                        )
                    }
                }
            )
        }
    ) { paddingValues ->
        val currentSession = session
        if (currentSession == null) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues),
                contentAlignment = Alignment.Center
            ) {
                CircularProgressIndicator()
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues)
                    .padding(horizontal = 16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                item {
                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.surfaceVariant
                        )
                    ) {
                        Column(modifier = Modifier.padding(12.dp)) {
                            Text(
                                text = formatEpochMs(currentSession.startedAtEpochMs),
                                style = MaterialTheme.typography.titleMedium,
                                color = MaterialTheme.colorScheme.onSurface
                            )
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = "Device: ${currentSession.deviceManufacturer} " +
                                    "${currentSession.deviceModel} (${currentSession.deviceName})",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Text(
                                text = "App version: ${currentSession.appVersion}",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Text(
                                text = "Duration: " + formatSessionDuration(
                                    currentSession.startedAtEpochMs,
                                    currentSession.endedAtEpochMs
                                ),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Text(
                                text = "Status: ${currentSession.status}",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Text(
                                text = "Session: ${currentSession.sessionDirectoryName}",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.tertiaryContent
                            )
                        }
                    }
                }
                item {
                    Text(
                        text = "Segments (${segments.size})",
                        style = MaterialTheme.typography.titleSmall,
                        color = MaterialTheme.colorScheme.onBackground
                    )
                }
                items(segments, key = { it.id }) { segment ->
                    SensorSegmentCard(segment)
                }
            }
        }
    }

    exportedZipPath?.let { path ->
        AlertDialog(
            onDismissRequest = { exportedZipPath = null },
            title = { Text("Session exported") },
            text = { Text(path) },
            confirmButton = {
                TextButton(onClick = { exportedZipPath = null }) {
                    Text("Close")
                }
            },
            dismissButton = {
                TextButton(onClick = {
                    val clipboard =
                        context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    clipboard.setPrimaryClip(ClipData.newPlainText("Sensor session zip", path))
                    Toast.makeText(context, "Path copied.", Toast.LENGTH_SHORT).show()
                }) {
                    Text("Copy path")
                }
            }
        )
    }
}

@Composable
private fun SensorSegmentCard(
    segment: com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSegmentEntity
) {
    val record = remember(segment.id) { MotionCaptureSyncMappings.segmentEntityToRecord(segment) }
    val label = record.correctedLabel ?: record.autoLabel
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = "#${record.sequenceIndex} ${record.stateName}",
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onSurface
                )
                Text(
                    text = record.reviewStatus.name,
                    style = MaterialTheme.typography.bodySmall,
                    color = when (record.reviewStatus) {
                        com.gabstra.myworkoutassistant.shared.motion.MotionCaptureReviewStatus.CONFIRMED,
                        com.gabstra.myworkoutassistant.shared.motion.MotionCaptureReviewStatus.RELABELED ->
                            MaterialTheme.colorScheme.primary
                        com.gabstra.myworkoutassistant.shared.motion.MotionCaptureReviewStatus.DROPPED ->
                            MaterialTheme.colorScheme.error
                        else -> MaterialTheme.colorScheme.tertiaryContent
                    }
                )
            }
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = "Kind: ${label.kind.name}" +
                    (label.exerciseName?.let { " | $it" } ?: ""),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                text = "Duration: " + formatSessionDuration(
                    record.startedAtEpochMs,
                    record.endedAtEpochMs
                ),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}
