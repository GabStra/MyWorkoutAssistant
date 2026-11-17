package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.composables.BreadcrumbScaffold

import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TimePicker
import androidx.compose.material3.TimePickerState
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.records.ExerciseSessionRecord
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.WorkoutTypes
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.composables.AppPrimaryOutlinedButton
import com.gabstra.myworkoutassistant.composables.AppSecondaryButton
import com.gabstra.myworkoutassistant.composables.CollapsibleSection
import com.gabstra.myworkoutassistant.composables.DialogOutlinedButton
import com.gabstra.myworkoutassistant.composables.FormSectionTitle
import com.gabstra.myworkoutassistant.composables.StandardDialog
import com.gabstra.myworkoutassistant.composables.StandardFilterDropdown
import com.gabstra.myworkoutassistant.composables.StandardFilterDropdownItem
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.composables.SwipeableTabs
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule
import com.gabstra.myworkoutassistant.shared.utils.ScheduleConflictChecker
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.util.Locale
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun WorkoutForm(
    onWorkoutUpsert: (Workout, List<WorkoutSchedule>) -> Unit,
    onCancel: () -> Unit,
    workout: Workout? = null,
    isSaving: Boolean = false,
    existingSchedules: List<WorkoutSchedule> = emptyList(),
    workoutPlanId: UUID? = null,
    availableExternalHeartRateSources: Set<HeartRateSource> = emptySet(),
) {
    // ---- state ----
    val workoutNameState = rememberSaveable { mutableStateOf(workout?.name ?: "") }
    val workoutDescriptionState = rememberSaveable { mutableStateOf(workout?.description ?: "") }
    val timesCompletedInAWeekState = rememberSaveable { mutableStateOf(workout?.timesCompletedInAWeek?.toString() ?: "0") }
    val heartRateSourceState = rememberSaveable {
        mutableStateOf(workout?.heartRateSource ?: HeartRateSource.WATCH_SENSOR)
    }
    // All sources that should connect and record together for this workout.
    val enabledHeartRateSourcesState = remember {
        mutableStateOf(workout?.enabledHeartRateSources ?: setOf(HeartRateSource.WATCH_SENSOR))
    }

    val selectedWorkoutType = rememberSaveable {
        mutableIntStateOf(workout?.type ?: ExerciseSessionRecord.EXERCISE_TYPE_STRENGTH_TRAINING)
    }
    val workoutTypeItems = remember {
        WorkoutTypes.WORKOUT_TYPE_STRING_TO_INT_MAP.entries.map { entry ->
            StandardFilterDropdownItem(
                value = entry.value,
                label = entry.key.replace('_', ' ').lowercase(Locale.ROOT)
                    .replaceFirstChar { if (it.isLowerCase()) it.titlecase(Locale.ROOT) else it.toString() }
            )
        }
    }
    val heartRateSourceItems = remember {
        HeartRateSource.entries.map { source ->
            StandardFilterDropdownItem(
                value = source,
                label = source.displayName()
            )
        }
    }

    val schedules = remember(existingSchedules) {
        mutableStateListOf<WorkoutSchedule>().apply {
            addAll(existingSchedules)
        }
    }
    val showScheduleDialog = remember { mutableStateOf(false) }
    val currentEditingSchedule = remember { mutableStateOf<WorkoutSchedule?>(null) }

    val showBatchScheduleDialog = remember { mutableStateOf(false) }

    var expandedSchedule by rememberSaveable { mutableStateOf(false) }

    val newGlobalId = remember { workout?.globalId ?: UUID.randomUUID() }

    val scrollState = rememberScrollState()
    val context = LocalContext.current

    Box(modifier = Modifier.fillMaxSize()) {
        BreadcrumbScaffold(
            showTopBarDivider = false,
            topBar = {
                TopAppBar(
                    title = {
                        Text(
                            modifier = Modifier
                                .fillMaxWidth()
                                .basicMarquee(iterations = Int.MAX_VALUE),
                            text = if (workout == null) {
                                stringResource(R.string.workout_form_add_title)
                            } else {
                                stringResource(R.string.workout_form_edit_title)
                            },
                            textAlign = TextAlign.Center,
                            style = MaterialTheme.typography.titleLarge
                        )
                    },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = Color.Transparent,
                        navigationIconContentColor = MaterialTheme.colorScheme.onBackground,
                        actionIconContentColor = MaterialTheme.colorScheme.onBackground
                    ),
                    navigationIcon = {
                        IconButton(onClick = onCancel, enabled = !isSaving) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                contentDescription = stringResource(R.string.workout_back_cd)
                            )
                        }
                    },
                    actions = {
                        // invisible icon to keep title centered like in ExerciseForm
                        IconButton(modifier = Modifier.alpha(0f), onClick = { }) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                contentDescription = stringResource(R.string.workout_back_cd)
                            )
                        }
                    }
                )
            }
        ) { padding ->
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .padding(vertical = Spacing.sm)
                    .verticalScroll(scrollState)
                    .padding(horizontal = Spacing.md),
            ) {
                // ----- Essentials -----
                FormSectionTitle(text = stringResource(R.string.workout_form_section_essentials))
                StyledCard(modifier = Modifier.fillMaxWidth()) {
                    Column(
                        modifier = Modifier.padding(Spacing.md),
                        verticalArrangement = Arrangement.spacedBy(Spacing.sm)
                    ) {
                        OutlinedTextField(
                            value = workoutNameState.value,
                            onValueChange = { workoutNameState.value = it },
                            label = { Text(stringResource(R.string.workout_form_name_label), style = MaterialTheme.typography.labelLarge) },
                            modifier = Modifier.fillMaxWidth(),
                            enabled = workout?.recurringSessionId == null,
                        )
                        if (workout?.recurringSessionId != null) {
                            Text(
                                text = stringResource(R.string.workout_form_rename_hint),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }

                        OutlinedTextField(
                            value = workoutDescriptionState.value,
                            onValueChange = { workoutDescriptionState.value = it },
                            label = { Text(stringResource(R.string.workout_form_description_label), style = MaterialTheme.typography.labelLarge) },
                            modifier = Modifier.fillMaxWidth(),
                            maxLines = 5,
                            singleLine = false
                        )

                        val typeLabel = remember(workoutTypeItems, selectedWorkoutType.intValue) {
                            workoutTypeItems.firstOrNull { it.value == selectedWorkoutType.intValue }?.label ?: ""
                        }
                        StandardFilterDropdown(
                            label = stringResource(R.string.workout_form_type_label),
                            selectedText = typeLabel,
                            items = workoutTypeItems,
                            onItemSelected = { selectedWorkoutType.intValue = it },
                            selectedValue = selectedWorkoutType.intValue,
                            modifier = Modifier.fillMaxWidth(),
                            isItemSelected = { it == selectedWorkoutType.intValue }
                        )

                        OutlinedTextField(
                            value = timesCompletedInAWeekState.value,
                            onValueChange = { input ->
                                if (input.isEmpty() || input.all { it.isDigit() }) {
                                    timesCompletedInAWeekState.value = input
                                }
                            },
                            label = { Text(stringResource(R.string.workout_form_target_sessions_label), style = MaterialTheme.typography.labelLarge) },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            modifier = Modifier.fillMaxWidth()
                        )

                        Text(
                            text = stringResource(R.string.workout_form_hr_sources_label),
                            style = MaterialTheme.typography.labelLarge
                        )
                        FlowRow(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            HeartRateSource.entries.forEach { source ->
                                val enabled = source in enabledHeartRateSourcesState.value
                                val configured = !source.isExternal ||
                                    source in availableExternalHeartRateSources
                                FilterChip(
                                    selected = enabled,
                                    onClick = {
                                        val current = enabledHeartRateSourcesState.value
                                        val updated = if (enabled) current - source else current + source
                                        if (updated.isEmpty()) return@FilterChip
                                        enabledHeartRateSourcesState.value = updated
                                        if (heartRateSourceState.value !in updated) {
                                            heartRateSourceState.value =
                                                HeartRateSource.entries.first { it in updated }
                                        }
                                    },
                                    enabled = configured || enabled,
                                    label = { Text(source.displayName()) },
                                )
                            }
                        }

                        val enabledItems = remember(
                            heartRateSourceItems,
                            enabledHeartRateSourcesState.value
                        ) {
                            heartRateSourceItems.filter {
                                it.value in enabledHeartRateSourcesState.value
                            }
                        }
                        val heartRateSourceLabel = remember(enabledItems, heartRateSourceState.value) {
                            enabledItems.firstOrNull { it.value == heartRateSourceState.value }?.label
                                ?: HeartRateSource.WATCH_SENSOR.displayName()
                        }
                        StandardFilterDropdown(
                            label = stringResource(R.string.workout_form_live_source_label),
                            selectedText = heartRateSourceLabel,
                            items = enabledItems,
                            onItemSelected = { heartRateSourceState.value = it },
                            selectedValue = heartRateSourceState.value,
                            modifier = Modifier.fillMaxWidth(),
                            isItemSelected = { it == heartRateSourceState.value }
                        )
                    }
                }

                Spacer(Modifier.height(Spacing.md))

                FormSectionTitle(text = stringResource(R.string.workout_form_section_schedule))
                val scheduleSummary = if (schedules.isEmpty()) {
                    stringResource(R.string.workout_form_no_alarms)
                } else {
                    pluralStringResource(R.plurals.workout_form_alarm_count, schedules.size, schedules.size)
                }
                CollapsibleSection(
                    title = stringResource(R.string.workout_form_alarms_title),
                    summary = scheduleSummary,
                    expanded = expandedSchedule,
                    onToggle = { expandedSchedule = !expandedSchedule }
                ) {
                    if (schedules.isEmpty()) {
                        Text(
                            text = stringResource(R.string.workout_form_no_alarms_body),
                            style = MaterialTheme.typography.bodyMedium
                        )
                    } else {
                        Column(verticalArrangement = Arrangement.spacedBy(Spacing.sm)) {
                            schedules.forEachIndexed { index, schedule ->
                                ScheduleListItem(
                                    schedule = schedule,
                                    index = index,
                                    onEdit = {
                                        currentEditingSchedule.value = schedule
                                        showScheduleDialog.value = true
                                    },
                                    onDelete = {
                                        schedules.removeAt(index)
                                    }
                                )
                            }
                        }
                    }

                    Spacer(Modifier.height(Spacing.md))

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(Spacing.md)
                    ) {
                        AppPrimaryOutlinedButton(
                            text = stringResource(R.string.workout_form_add_one),
                            onClick = {
                                currentEditingSchedule.value = null
                                showScheduleDialog.value = true
                            },
                            modifier = Modifier.weight(1f)
                        )

                        AppPrimaryOutlinedButton(
                            text = stringResource(R.string.workout_form_add_multiple),
                            onClick = { showBatchScheduleDialog.value = true },
                            modifier = Modifier.weight(1f)
                        )
                    }
                }

                Spacer(Modifier.height(Spacing.xl))

                // ---- Actions ----------------------------------------------------
                val canBeSaved = workoutNameState.value.isNotBlank()

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(Spacing.md),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    AppSecondaryButton(
                        text = stringResource(R.string.workout_cancel),
                        onClick = onCancel,
                        enabled = !isSaving,
                        modifier = Modifier.weight(1f)
                    )

                    AppPrimaryButton(
                        text = stringResource(R.string.workout_save),
                        onClick = {
                            val enabledSources = enabledHeartRateSourcesState.value +
                                heartRateSourceState.value
                            val unconfigured = enabledSources.firstOrNull { source ->
                                source.isExternal && source !in availableExternalHeartRateSources
                            }
                            if (unconfigured != null) {
                                Toast.makeText(
                                    context,
                                    context.getString(
                                        R.string.workout_form_configure_source_first,
                                        unconfigured.displayName()
                                    ),
                                    Toast.LENGTH_SHORT
                                ).show()
                                return@AppPrimaryButton
                            }
                            val newWorkout = Workout(
                                id = workout?.id ?: UUID.randomUUID(),
                                name = workoutNameState.value.trim(),
                                description = workoutDescriptionState.value.trim(),
                                workoutComponents = workout?.workoutComponents ?: listOf(),
                                heartRateSource = heartRateSourceState.value,
                                heartRateSources = enabledSources,
                                creationDate = LocalDate.now(),
                                order = workout?.order ?: 0,
                                timesCompletedInAWeek = timesCompletedInAWeekState.value.toIntOrNull(),
                                globalId = newGlobalId,
                                type = selectedWorkoutType.intValue,
                                workoutPlanId = workoutPlanId ?: workout?.workoutPlanId,
                                recurringSessionId = workout?.recurringSessionId,
                                prescriptionOrdinal = workout?.prescriptionOrdinal,
                                prescriptionLabel = workout?.prescriptionLabel,
                            )
                            onWorkoutUpsert(newWorkout, schedules.toList())
                        },
                        enabled = canBeSaved && !isSaving,
                        modifier = Modifier.weight(1f)
                    )
                }

                Spacer(Modifier.height(Spacing.xl))
            }
        }
        if (isSaving) {
            val interactionSource = remember { MutableInteractionSource() }
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.75f))
                    .clickable(
                        interactionSource = interactionSource,
                        indication = null,
                        onClick = {}
                    ),
                contentAlignment = Alignment.Center
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    CircularProgressIndicator()
                    Spacer(Modifier.height(Spacing.md))
                    Text(text = stringResource(R.string.workout_form_saving), style = MaterialTheme.typography.bodyLarge)
                }
            }
        }
    }

    // ---- Dialogs -----------------------------------------------------------
    if (showScheduleDialog.value) {
        ScheduleDialog(
            schedule = currentEditingSchedule.value,
            workoutId = newGlobalId,
            existingSchedules = schedules.toList(),
            onDismiss = { showScheduleDialog.value = false },
            onSave = { newSchedule ->
                val idx = schedules.indexOfFirst { it.id == newSchedule.id }
                if (idx >= 0) schedules[idx] = newSchedule else schedules.add(newSchedule)
                showScheduleDialog.value = false
            }
        )
    }

    if (showBatchScheduleDialog.value) {
        BatchScheduleDialog(
            workoutId = newGlobalId,
            existingSchedules = schedules.toList(),
            onDismiss = { showBatchScheduleDialog.value = false },
            onSave = { newSchedules ->
                schedules.addAll(newSchedules)
                showBatchScheduleDialog.value = false
            }
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ScheduleDialog(
    schedule: WorkoutSchedule?,
    workoutId: UUID,
    existingSchedules: List<WorkoutSchedule>,
    onDismiss: () -> Unit,
    onSave: (WorkoutSchedule) -> Unit
) {
    val context = LocalContext.current
    val isEditing = schedule != null

    val labelState = rememberSaveable { mutableStateOf(schedule?.label ?: "") }
    val hourState = rememberSaveable { mutableIntStateOf(schedule?.hour ?: 8) }
    val minuteState = rememberSaveable { mutableIntStateOf(schedule?.minute ?: 0) }
    val isEnabledState = rememberSaveable { mutableStateOf(schedule?.isEnabled ?: true) }

    val useSpecificDate = rememberSaveable { mutableStateOf(schedule?.specificDate != null) }

    val daysOfWeekState = rememberSaveable { mutableIntStateOf(schedule?.daysOfWeek ?: 0) }

    val datePickerState = rememberDatePickerState(
        initialSelectedDateMillis = schedule?.specificDate?.atStartOfDay(ZoneId.systemDefault())?.toInstant()?.toEpochMilli()
            ?: System.currentTimeMillis()
    )
    val showDatePicker = remember { mutableStateOf(false) }

    val timePickerState = rememberTimePickerState(
        initialHour = hourState.intValue,
        initialMinute = minuteState.intValue
    )
    val showTimePicker = remember { mutableStateOf(false) }

    StandardDialog(
        onDismissRequest = onDismiss,
        title = if (isEditing) {
            stringResource(R.string.workout_form_edit_alarm)
        } else {
            stringResource(R.string.workout_form_add_alarm)
        },
        body = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(Spacing.sm)
            ) {
                OutlinedTextField(
                    value = labelState.value,
                    onValueChange = { labelState.value = it },
                    label = { Text(stringResource(R.string.workout_form_label_optional), style = MaterialTheme.typography.labelLarge) },
                    modifier = Modifier.fillMaxWidth()
                )

                Spacer(Modifier.height(Spacing.lg))
                Text(stringResource(R.string.workout_form_time_label), style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(Spacing.sm))
                AppPrimaryOutlinedButton(
                    text = "${hourState.intValue}:${minuteState.intValue.toString().padStart(2, '0')}",
                    onClick = { showTimePicker.value = true },
                    modifier = Modifier.fillMaxWidth()
                )

                ListItem(
                    colors = ListItemDefaults.colors().copy(containerColor = Color.Transparent),
                    headlineContent = { Text(stringResource(R.string.workout_form_use_specific_date), style = MaterialTheme.typography.bodyLarge) },
                    trailingContent = {
                        Switch(
                            checked = useSpecificDate.value,
                            onCheckedChange = { useSpecificDate.value = it }
                        )
                    }
                )
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

                Spacer(Modifier.height(Spacing.lg))

                if (useSpecificDate.value) {
                    val date = datePickerState.selectedDateMillis?.let {
                        Instant.ofEpochMilli(it).atZone(ZoneId.systemDefault()).toLocalDate()
                    } ?: LocalDate.now()

                    Text(stringResource(R.string.workout_form_date_label), style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(Spacing.sm))
                    AppPrimaryOutlinedButton(
                        text = date.toString(),
                        onClick = { showDatePicker.value = true },
                        modifier = Modifier.fillMaxWidth()
                    )
                } else {
                    Text(stringResource(R.string.workout_form_days_of_week), style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(Spacing.sm))
                    WeekdaySelectionRow(
                        days = listOf(
                            stringResource(R.string.workout_day_mon),
                            stringResource(R.string.workout_day_tue),
                            stringResource(R.string.workout_day_wed),
                            stringResource(R.string.workout_day_thu),
                        ),
                        bitValues = listOf(2, 4, 8, 16),
                        daysOfWeekState = daysOfWeekState
                    )
                    WeekdaySelectionRow(
                        days = listOf(
                            stringResource(R.string.workout_day_fri),
                            stringResource(R.string.workout_day_sat),
                            stringResource(R.string.workout_day_sun),
                            "",
                        ),
                        bitValues = listOf(32, 64, 1, 0),
                        daysOfWeekState = daysOfWeekState,
                        showLastCheckbox = false
                    )
                }

                Spacer(Modifier.height(Spacing.lg))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

                ListItem(
                    colors = ListItemDefaults.colors().copy(containerColor = Color.Transparent),
                    headlineContent = { Text(stringResource(R.string.workout_form_enabled), style = MaterialTheme.typography.bodyLarge) },
                    trailingContent = {
                        Switch(
                            checked = isEnabledState.value,
                            onCheckedChange = { isEnabledState.value = it }
                        )
                    }
                )
            }
        },
        confirmText = stringResource(R.string.workout_save),
        onConfirm = {
            val specificDate = if (useSpecificDate.value) {
                datePickerState.selectedDateMillis?.let {
                    Instant.ofEpochMilli(it).atZone(ZoneId.systemDefault()).toLocalDate()
                }
            } else null

            val validationError = validateAlarmScheduleInput(
                useSpecificDate = useSpecificDate.value,
                specificDate = specificDate,
                hour = hourState.intValue,
                minute = minuteState.intValue,
                daysOfWeek = daysOfWeekState.intValue
            )

            if (validationError != null) {
                Toast.makeText(context, context.getString(validationError), Toast.LENGTH_LONG).show()
            } else {
                val newSchedule = WorkoutSchedule(
                    id = schedule?.id ?: UUID.randomUUID(),
                    workoutId = workoutId,
                    label = labelState.value,
                    hour = hourState.intValue,
                    minute = minuteState.intValue,
                    isEnabled = isEnabledState.value,
                    daysOfWeek = if (useSpecificDate.value) 0 else daysOfWeekState.intValue,
                    specificDate = specificDate,
                    hasExecuted = resolveEditedScheduleHasExecuted(
                        existingSchedule = schedule,
                        specificDate = specificDate,
                        hour = hourState.intValue,
                        minute = minuteState.intValue
                    )
                )

                // Check for conflicts
                val conflicts = ScheduleConflictChecker.checkScheduleConflicts(
                    newSchedules = listOf(newSchedule),
                    existingSchedules = existingSchedules.filter { it.id != newSchedule.id }
                )

                if (conflicts.isNotEmpty()) {
                    val errorMessage = ScheduleConflictChecker.formatConflictMessage(conflicts)
                    Toast.makeText(context, errorMessage, Toast.LENGTH_LONG).show()
                } else {
                    onSave(newSchedule)
                }
            }
        },
        dismissText = stringResource(R.string.workout_cancel),
        onDismissButton = onDismiss
    )

    if (showTimePicker.value) {
        TimePickerDialog(
            onDismiss = { showTimePicker.value = false },
            onConfirm = {
                hourState.intValue = timePickerState.hour
                minuteState.intValue = timePickerState.minute
                showTimePicker.value = false
            },
            timePickerState = timePickerState
        )
    }

    if (showDatePicker.value) {
        DatePickerDialog(
            onDismissRequest = { showDatePicker.value = false },
            confirmButton = {
                DialogOutlinedButton(
                    text = stringResource(R.string.workout_ok),
                    onClick = { showDatePicker.value = false }
                )
            },
            dismissButton = {
                DialogOutlinedButton(
                    text = stringResource(R.string.workout_cancel),
                    onClick = { showDatePicker.value = false }
                )
            }
        ) { DatePicker(state = datePickerState) }
    }
}

internal fun validateAlarmScheduleInput(
    useSpecificDate: Boolean,
    specificDate: LocalDate?,
    hour: Int,
    minute: Int,
    daysOfWeek: Int,
    now: LocalDateTime = LocalDateTime.now()
): Int? {
    if (!useSpecificDate && daysOfWeek <= 0) {
        return R.string.workout_form_alarm_error_select_day
    }

    if (useSpecificDate) {
        val triggerDate = specificDate ?: return R.string.workout_form_alarm_error_pick_date
        if (!triggerDate.atTime(hour, minute).isAfter(now)) {
            return R.string.workout_form_alarm_error_future_date
        }
    }

    return null
}

internal fun resolveEditedScheduleHasExecuted(
    existingSchedule: WorkoutSchedule?,
    specificDate: LocalDate?,
    hour: Int,
    minute: Int
): Boolean {
    if (existingSchedule == null || specificDate == null) {
        return false
    }

    val isSameOneTimeTrigger =
        existingSchedule.daysOfWeek == 0 &&
            existingSchedule.specificDate == specificDate &&
            existingSchedule.hour == hour &&
            existingSchedule.minute == minute

    return existingSchedule.hasExecuted && isSameOneTimeTrigger
}

@Composable
fun WeekdaySelectionRow(
    days: List<String>,
    bitValues: List<Int>,
    daysOfWeekState: androidx.compose.runtime.MutableIntState,
    showLastCheckbox: Boolean = true
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        days.forEachIndexed { index, day ->
            if (index == days.lastIndex && !showLastCheckbox) {
                Box(modifier = Modifier.width(48.dp))
            } else if (day.isNotEmpty()) {
                DayOfWeekCheckbox(
                    day = day,
                    isChecked = (daysOfWeekState.intValue and bitValues[index]) != 0,
                    onCheckedChange = { checked ->
                        daysOfWeekState.intValue = if (checked) {
                            daysOfWeekState.intValue or bitValues[index]
                        } else {
                            daysOfWeekState.intValue and bitValues[index].inv()
                        }
                    }
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TimePickerDialog(
    onDismiss: () -> Unit,
    onConfirm: () -> Unit,
    timePickerState: TimePickerState
) {
    StandardDialog(
        onDismissRequest = onDismiss,
        title = stringResource(R.string.workout_form_choose_time),
        body = { TimePicker(state = timePickerState) },
        confirmText = stringResource(R.string.workout_ok),
        onConfirm = onConfirm,
        dismissText = stringResource(R.string.workout_cancel),
        onDismissButton = onDismiss
    )
}

@Composable
fun DayOfWeekCheckbox(
    day: String,
    isChecked: Boolean,
    onCheckedChange: (Boolean) -> Unit
) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(text = day, style = MaterialTheme.typography.bodySmall)
        androidx.compose.material3.Checkbox(
            checked = isChecked,
            onCheckedChange = onCheckedChange
        )
    }
}

private const val WeekendDaysBitmask = 1 or 64 // Sunday | Saturday

@Composable
fun getDaysOfWeekString(daysOfWeek: Int): String {
    val dayPairs = listOf(
        1 to stringResource(R.string.workout_day_sun),
        2 to stringResource(R.string.workout_day_mon),
        4 to stringResource(R.string.workout_day_tue),
        8 to stringResource(R.string.workout_day_wed),
        16 to stringResource(R.string.workout_day_thu),
        32 to stringResource(R.string.workout_day_fri),
        64 to stringResource(R.string.workout_day_sat)
    )
    val days = dayPairs.filter { (bit, _) -> (daysOfWeek and bit) != 0 }.map { it.second }
    return when {
        days.isEmpty() -> stringResource(R.string.workout_form_alarm_no_days)
        days.size == 7 -> stringResource(R.string.workout_form_alarm_every_day)
        days.size == 5 && (daysOfWeek and WeekendDaysBitmask) == 0 -> stringResource(R.string.workout_form_alarm_weekdays)
        days.size == 2 && (daysOfWeek and WeekendDaysBitmask) == WeekendDaysBitmask -> stringResource(R.string.workout_form_alarm_weekends)
        else -> days.joinToString(", ")
    }
}

@Composable
fun ScheduleListItem(
    schedule: WorkoutSchedule,
    index: Int,
    onEdit: () -> Unit,
    onDelete: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = Spacing.sm),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Spacing.md)
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = if (schedule.label.isNotEmpty()) {
                    schedule.label
                } else {
                    stringResource(R.string.workout_form_alarm_n, index + 1)
                },
                style = MaterialTheme.typography.bodyMedium
            )
            Text(
                text = if (schedule.specificDate != null) {
                    stringResource(
                        R.string.workout_form_alarm_on_date_at_time,
                        schedule.specificDate.toString(),
                        "${schedule.hour}:${schedule.minute.toString().padStart(2, '0')}",
                    )
                } else {
                    val days = getDaysOfWeekString(schedule.daysOfWeek)
                    stringResource(
                        R.string.workout_form_alarm_days_at_time,
                        days,
                        "${schedule.hour}:${schedule.minute.toString().padStart(2, '0')}",
                    )
                },
                style = MaterialTheme.typography.bodySmall
            )
        }
        Text(text = stringResource(R.string.workout_form_edit_action), modifier = Modifier.clickable { onEdit() })
        Text(text = stringResource(R.string.workout_form_delete_action), modifier = Modifier.clickable { onDelete() })
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BatchScheduleDialog(
    workoutId: UUID,
    existingSchedules: List<WorkoutSchedule>,
    onDismiss: () -> Unit,
    onSave: (List<WorkoutSchedule>) -> Unit
) {
    val context = LocalContext.current
    val selectedTabIndex = rememberSaveable { mutableIntStateOf(0) }

    val labelPrefixState = rememberSaveable { mutableStateOf("Schedule") }
    val isEnabledState = rememberSaveable { mutableStateOf(true) }

    val startHourState = rememberSaveable { mutableIntStateOf(8) }
    val startMinuteState = rememberSaveable { mutableIntStateOf(0) }
    val endHourState = rememberSaveable { mutableIntStateOf(16) }
    val endMinuteState = rememberSaveable { mutableIntStateOf(0) }

    val currentPickerMode = remember { mutableStateOf("") } // "start" or "end"
    val showTimePicker = remember { mutableStateOf(false) }
    val timePickerState = rememberTimePickerState(initialHour = 8, initialMinute = 0)

    val intervalHoursState = rememberSaveable { mutableStateOf("0") }
    val intervalMinutesState = rememberSaveable { mutableStateOf("30") }

    val daysOfWeekState = rememberSaveable { mutableIntStateOf(0) }

    val datePickerState = rememberDatePickerState(initialSelectedDateMillis = System.currentTimeMillis())
    val showDatePicker = remember { mutableStateOf(false) }

    StandardDialog(
        onDismissRequest = onDismiss,
        title = stringResource(R.string.workout_form_add_multiple_alarms),
        body = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
            ) {
                SwipeableTabs(
                    tabTitles = listOf(
                        stringResource(R.string.workout_form_tab_one_time),
                        stringResource(R.string.workout_form_tab_recurring),
                    ),
                    selectedTabIndex = selectedTabIndex.intValue,
                    onTabSelected = { selectedTabIndex.intValue = it },
                    containerColor = Color.Transparent,
                    contentColor = MaterialTheme.colorScheme.onBackground,
                    selectedContentColor = MaterialTheme.colorScheme.primary,
                    unselectedContentColor = MaterialTheme.colorScheme.onBackground,
                    renderPager = false
                )

                Spacer(Modifier.height(Spacing.lg))

                OutlinedTextField(
                    value = labelPrefixState.value,
                    onValueChange = { labelPrefixState.value = it },
                    label = { Text(stringResource(R.string.workout_form_label_prefix), style = MaterialTheme.typography.labelLarge) },
                    modifier = Modifier.fillMaxWidth()
                )

                Spacer(Modifier.height(Spacing.lg))

                Text(stringResource(R.string.workout_form_time_range), style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(Spacing.sm))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(Spacing.md),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(stringResource(R.string.workout_form_from), style = MaterialTheme.typography.bodyMedium)
                        Spacer(Modifier.height(Spacing.xs))
                        AppPrimaryOutlinedButton(
                            text = "${startHourState.intValue}:${startMinuteState.intValue.toString().padStart(2, '0')}",
                            onClick = {
                                timePickerState.hour = startHourState.intValue
                                timePickerState.minute = startMinuteState.intValue
                                currentPickerMode.value = "start"
                                showTimePicker.value = true
                            },
                            modifier = Modifier.fillMaxWidth()
                        )
                    }

                    Column(modifier = Modifier.weight(1f)) {
                        Text(stringResource(R.string.workout_form_to), style = MaterialTheme.typography.bodyMedium)
                        Spacer(Modifier.height(Spacing.xs))
                        AppPrimaryOutlinedButton(
                            text = "${endHourState.intValue}:${endMinuteState.intValue.toString().padStart(2, '0')}",
                            onClick = {
                                timePickerState.hour = endHourState.intValue
                                timePickerState.minute = endMinuteState.intValue
                                currentPickerMode.value = "end"
                                showTimePicker.value = true
                            },
                            modifier = Modifier.fillMaxWidth()
                        )
                    }
                }

                Spacer(Modifier.height(Spacing.lg))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                Spacer(Modifier.height(Spacing.lg))

                Text(stringResource(R.string.workout_form_interval), style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(Spacing.sm))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(
                        value = intervalHoursState.value,
                        onValueChange = { v -> if (v.isEmpty() || v.all { it.isDigit() }) intervalHoursState.value = v },
                        label = { Text(stringResource(R.string.workout_form_hours), style = MaterialTheme.typography.labelLarge) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.weight(1f)
                    )
                    Spacer(Modifier.width(Spacing.md))
                    OutlinedTextField(
                        value = intervalMinutesState.value,
                        onValueChange = { v -> if (v.isEmpty() || v.all { it.isDigit() }) intervalMinutesState.value = v },
                        label = { Text(stringResource(R.string.workout_form_minutes), style = MaterialTheme.typography.labelLarge) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.weight(1f)
                    )
                }

                Spacer(Modifier.height(Spacing.lg))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                Spacer(Modifier.height(Spacing.lg))

                if (selectedTabIndex.intValue == 0) {
                    val date = datePickerState.selectedDateMillis?.let {
                        Instant.ofEpochMilli(it).atZone(ZoneId.systemDefault()).toLocalDate()
                    } ?: LocalDate.now()
                    Text(stringResource(R.string.workout_form_date_label), style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(Spacing.sm))
                    AppPrimaryOutlinedButton(
                        text = date.toString(),
                        onClick = { showDatePicker.value = true },
                        modifier = Modifier.fillMaxWidth()
                    )
                } else {
                    Text(stringResource(R.string.workout_form_days_of_week), style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(Spacing.sm))
                    WeekdaySelectionRow(
                        days = listOf(
                            stringResource(R.string.workout_day_mon),
                            stringResource(R.string.workout_day_tue),
                            stringResource(R.string.workout_day_wed),
                            stringResource(R.string.workout_day_thu),
                        ),
                        bitValues = listOf(2, 4, 8, 16),
                        daysOfWeekState = daysOfWeekState
                    )
                    WeekdaySelectionRow(
                        days = listOf(
                            stringResource(R.string.workout_day_fri),
                            stringResource(R.string.workout_day_sat),
                            stringResource(R.string.workout_day_sun),
                            "",
                        ),
                        bitValues = listOf(32, 64, 1, 0),
                        daysOfWeekState = daysOfWeekState,
                        showLastCheckbox = false
                    )
                }

                Spacer(Modifier.height(Spacing.lg))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

                ListItem(
                    colors = ListItemDefaults.colors().copy(containerColor = Color.Transparent),
                    headlineContent = { Text(stringResource(R.string.workout_form_enable_all), style = MaterialTheme.typography.bodyLarge) },
                    trailingContent = {
                        Switch(
                            checked = isEnabledState.value,
                            onCheckedChange = { isEnabledState.value = it }
                        )
                    }
                )
            }
        },
        confirmText = stringResource(R.string.workout_save),
        onConfirm = {
            val list = mutableListOf<WorkoutSchedule>()
            val startTotal = startHourState.intValue * 60 + startMinuteState.intValue
            val endTotal = endHourState.intValue * 60 + endMinuteState.intValue
            val interval = ((intervalHoursState.value.toIntOrNull() ?: 0) * 60 + (intervalMinutesState.value.toIntOrNull()
                ?: 30)).coerceAtLeast(1)

            var t = startTotal
            var count = 1
            while (t <= endTotal) {
                val hour = t / 60
                val minute = t % 60
                val specificDate = if (selectedTabIndex.intValue == 0) {
                    datePickerState.selectedDateMillis?.let {
                        Instant.ofEpochMilli(it).atZone(ZoneId.systemDefault()).toLocalDate()
                    }
                } else null

                list.add(
                    WorkoutSchedule(
                        id = UUID.randomUUID(),
                        workoutId = workoutId,
                        label = "${labelPrefixState.value} $count",
                        hour = hour,
                        minute = minute,
                        isEnabled = isEnabledState.value,
                        daysOfWeek = if (selectedTabIndex.intValue == 1) daysOfWeekState.intValue else 0,
                        specificDate = specificDate,
                        hasExecuted = false
                    )
                )

                t += interval
                count++
            }

            val validationError =
                when {
                    list.isEmpty() -> R.string.workout_form_time_range_error
                    else -> list.firstNotNullOfOrNull { schedule ->
                        validateAlarmScheduleInput(
                            useSpecificDate = schedule.specificDate != null,
                            specificDate = schedule.specificDate,
                            hour = schedule.hour,
                            minute = schedule.minute,
                            daysOfWeek = schedule.daysOfWeek
                        )
                    }
                }

            if (validationError != null) {
                Toast.makeText(context, context.getString(validationError), Toast.LENGTH_LONG).show()
            } else {
                // Check for conflicts
                val conflicts = ScheduleConflictChecker.checkScheduleConflicts(
                    newSchedules = list,
                    existingSchedules = existingSchedules
                )

                if (conflicts.isNotEmpty()) {
                    val errorMessage = ScheduleConflictChecker.formatConflictMessage(conflicts)
                    Toast.makeText(context, errorMessage, Toast.LENGTH_LONG).show()
                } else {
                    onSave(list)
                }
            }
        },
        dismissText = stringResource(R.string.workout_cancel),
        onDismissButton = onDismiss
    )

    if (showTimePicker.value) {
        TimePickerDialog(
            onDismiss = { showTimePicker.value = false },
            onConfirm = {
                if (currentPickerMode.value == "start") {
                    startHourState.intValue = timePickerState.hour
                    startMinuteState.intValue = timePickerState.minute
                } else if (currentPickerMode.value == "end") {
                    endHourState.intValue = timePickerState.hour
                    endMinuteState.intValue = timePickerState.minute
                }
                showTimePicker.value = false
            },
            timePickerState = timePickerState
        )
    }

    if (showDatePicker.value) {
        DatePickerDialog(
            onDismissRequest = { showDatePicker.value = false },
            confirmButton = {
                DialogOutlinedButton(
                    text = stringResource(R.string.workout_ok),
                    onClick = { showDatePicker.value = false }
                )
            },
            dismissButton = {
                DialogOutlinedButton(
                    text = stringResource(R.string.workout_cancel),
                    onClick = { showDatePicker.value = false }
                )
            }
        ) { DatePicker(state = datePickerState) }
    }
}



