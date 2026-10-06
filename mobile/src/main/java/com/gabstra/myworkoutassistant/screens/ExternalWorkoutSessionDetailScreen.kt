package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.composables.BreadcrumbScaffold

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLocale
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.HeartRateSessionCard
import com.gabstra.myworkoutassistant.composables.PrimarySurface
import com.gabstra.myworkoutassistant.composables.SecondarySurface
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.healthconnect.external.ExternalHealthConnectSessionDatabase
import com.gabstra.myworkoutassistant.healthconnect.external.ExternalHealthConnectSessionEntity
import com.gabstra.myworkoutassistant.healthconnect.external.normalizeExternalHeartRateSamples
import com.gabstra.myworkoutassistant.heart_rate.analyzeHeartRateSession
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExternalWorkoutSessionDetailScreen(
    appViewModel: AppViewModel,
    sessionId: String,
    onGoBack: () -> Unit,
) {
    val context = LocalContext.current
    val database = remember(context) { ExternalHealthConnectSessionDatabase.getDatabase(context) }
    val currentLocale = LocalLocale.current.platformLocale
    val dateFormatter = remember(currentLocale) {
        DateTimeFormatter.ofPattern("dd/MM/yy", currentLocale)
    }
    val timeFormatter = remember(currentLocale) {
        DateTimeFormatter.ofPattern("HH:mm", currentLocale)
    }

    var session by remember(sessionId) { mutableStateOf<ExternalHealthConnectSessionEntity?>(null) }
    var hasLoaded by remember(sessionId) { mutableStateOf(false) }

    LaunchedEffect(sessionId) {
        hasLoaded = false
        session = withContext(Dispatchers.IO) {
            database.externalHealthConnectSessionDao().getById(sessionId)
        }
        hasLoaded = true
    }

    val analysis = remember(
        session,
        appViewModel.userAge.value,
        appViewModel.workoutStore.measuredMaxHeartRate,
        appViewModel.workoutStore.restingHeartRate,
    ) {
        session?.let { currentSession ->
            analyzeHeartRateSession(
                heartRateSeries = normalizeExternalHeartRateSamples(
                    samples = currentSession.heartRateSamples,
                    durationSeconds = currentSession.durationSeconds,
                ),
                durationSeconds = currentSession.durationSeconds,
                userAge = appViewModel.userAge.value,
                measuredMaxHeartRate = appViewModel.workoutStore.measuredMaxHeartRate,
                restingHeartRate = appViewModel.workoutStore.restingHeartRate,
            )
        }
    }

    BreadcrumbScaffold(
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                    titleContentColor = MaterialTheme.colorScheme.onBackground,
                    navigationIconContentColor = MaterialTheme.colorScheme.onBackground,
                    actionIconContentColor = MaterialTheme.colorScheme.onBackground,
                ),
                title = {
                    Text(
                        modifier = Modifier.fillMaxWidth(),
                        textAlign = TextAlign.Center,
                        text = "External session",
                        maxLines = 2,
                        style = MaterialTheme.typography.titleLarge,
                        color = MaterialTheme.colorScheme.onBackground,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onGoBack) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back",
                        )
                    }
                },
                actions = {
                    Box(modifier = Modifier.size(48.dp))
                },
            )
        },
    ) { paddingValues ->
        when {
            !hasLoaded -> {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(paddingValues),
                    contentAlignment = Alignment.Center,
                ) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(32.dp),
                        color = MaterialTheme.colorScheme.primary,
                        trackColor = MediumDarkGray,
                    )
                }
            }

            session == null -> {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(paddingValues),
                    contentAlignment = Alignment.Center,
                ) {
                    PrimarySurface(modifier = Modifier.padding(Spacing.md)) {
                        Text(
                            modifier = Modifier.padding(Spacing.md),
                            text = "External session not found.",
                            color = MaterialTheme.colorScheme.onBackground,
                            textAlign = TextAlign.Center,
                        )
                    }
                }
            }

            else -> {
                val currentSession = session!!
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(paddingValues)
                        .verticalScroll(rememberScrollState())
                        .padding(horizontal = Spacing.md),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Spacer(modifier = Modifier.height(10.dp))

                    PrimarySurface {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(Spacing.md),
                            verticalArrangement = Arrangement.spacedBy(Spacing.md),
                        ) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.Top,
                            ) {
                                Column(
                                    modifier = Modifier.weight(1f),
                                    verticalArrangement = Arrangement.spacedBy(4.dp),
                                ) {
                                    Text(
                                        text = currentSession.title ?: currentSession.exerciseTypeLabel,
                                        color = MaterialTheme.colorScheme.onBackground,
                                        style = MaterialTheme.typography.titleMedium,
                                        maxLines = 2,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                    if (currentSession.title != null) {
                                        Text(
                                            text = currentSession.exerciseTypeLabel,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                            style = MaterialTheme.typography.bodyMedium,
                                        )
                                    }
                                }
                                Spacer(modifier = Modifier.width(Spacing.sm))
                                ExternalSessionBadge()
                            }

                            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

                            Column(
                                modifier = Modifier.fillMaxWidth(),
                                verticalArrangement = Arrangement.spacedBy(12.dp),
                            ) {
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.spacedBy(Spacing.md),
                                    verticalAlignment = Alignment.Top,
                                ) {
                                    SessionDetailRow(
                                        modifier = Modifier.weight(1f),
                                        label = "Date",
                                        value = currentSession.startTime.format(dateFormatter),
                                    )
                                    SessionDetailRow(
                                        modifier = Modifier.weight(1f),
                                        label = "Duration",
                                        value = formatTime(currentSession.durationSeconds),
                                    )
                                }
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.spacedBy(Spacing.md),
                                    verticalAlignment = Alignment.Top,
                                ) {
                                    SessionDetailRow(
                                        modifier = Modifier.weight(1f),
                                        label = "Start time",
                                        value = currentSession.startTime.format(timeFormatter),
                                    )
                                    SessionDetailRow(
                                        modifier = Modifier.weight(1f),
                                        label = "End time",
                                        value = currentSession.endTime.format(timeFormatter),
                                    )
                                }
                            }
                        }
                    }

                    if (analysis != null) {
                        HeartRateSessionCard(
                            title = "Heart rate during workout",
                            analysis = analysis,
                            userAge = appViewModel.userAge.value,
                            measuredMaxHeartRate = appViewModel.workoutStore.measuredMaxHeartRate,
                            restingHeartRate = appViewModel.workoutStore.restingHeartRate,
                        )
                    } else {
                        PrimarySurface {
                            Text(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(Spacing.md),
                                text = "No heart rate data for this session.",
                                color = MaterialTheme.colorScheme.onBackground,
                                style = MaterialTheme.typography.bodyMedium,
                                textAlign = TextAlign.Center,
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(16.dp))
                }
            }
        }
    }
}

@Composable
private fun ExternalSessionBadge() {
    SecondarySurface {
        Text(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
            text = "Health Connect",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
    }
}

@Composable
private fun SessionDetailRow(
    modifier: Modifier = Modifier,
    label: String,
    value: String,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
        Text(
            text = value,
            color = MaterialTheme.colorScheme.onBackground,
            style = MaterialTheme.typography.bodyLarge,
        )
    }
}
