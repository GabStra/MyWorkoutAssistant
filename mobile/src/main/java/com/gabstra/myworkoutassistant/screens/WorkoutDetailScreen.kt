package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import android.content.Context
import android.util.Log
import android.widget.Toast
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.relocation.BringIntoViewRequester
import androidx.compose.foundation.relocation.bringIntoViewRequester
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.Block
import androidx.compose.material.icons.filled.CheckBox
import androidx.compose.material.icons.filled.CheckBoxOutlineBlank
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.ChevronLeft
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.MoveDown
import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.VerticalDivider
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.edit
import androidx.health.connect.client.HealthConnectClient
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.ActiveScheduleCard
import com.gabstra.myworkoutassistant.composables.AppDropdownMenu
import com.gabstra.myworkoutassistant.composables.AppDropdownMenuItem
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.composables.ExerciseRenderer
import com.gabstra.myworkoutassistant.composables.AppPrimaryOutlinedButton
import com.gabstra.myworkoutassistant.composables.GenericButtonWithMenu
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.LoadingOverlay
import com.gabstra.myworkoutassistant.composables.MenuItem
import com.gabstra.myworkoutassistant.composables.MoveExercisesToWorkoutDialog
import com.gabstra.myworkoutassistant.composables.SetRestRowCard
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.composables.SupersetRenderer
import com.gabstra.myworkoutassistant.composables.SwipeableTabs
import com.gabstra.myworkoutassistant.composables.swipeToAdjacentTab
import com.gabstra.myworkoutassistant.composables.rememberDebouncedSavingVisible
import com.gabstra.myworkoutassistant.ensureRestSeparatedByExercises
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.getEnabledStatusOfWorkoutComponent
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.cloneWorkoutComponent
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.gabstra.myworkoutassistant.shared.workout.ui.InterruptedWorkoutCopy
import com.gabstra.myworkoutassistant.verticalColumnScrollbarContainer
import com.gabstra.myworkoutassistant.workout.CustomDialogYesOnLongPress
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.UUID

@Composable
fun Menu(
    onEditWorkout: () -> Unit,
    onClearHistory: () -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }

    Box(
        modifier = Modifier.wrapContentSize(Alignment.TopEnd)
    ) {
        IconButton(onClick = { expanded = !expanded }) {
            Icon(
                imageVector = Icons.Default.MoreVert,
                contentDescription = "More"
            )
        }

        AppDropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false }
        ) {
            AppDropdownMenuItem(
                text = { Text(text = "Edit Workout", fontWeight = FontWeight.Normal) },
                onClick = {
                    onEditWorkout()
                    expanded = false
                }
            )
            HorizontalDivider(
                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f)
            )
            AppDropdownMenuItem(
                text = { Text(text = "Clear History", fontWeight = FontWeight.Normal) },
                onClick = {
                    onClearHistory()
                    expanded = false
                }
            )
        }
    }
}


@Composable
fun WorkoutComponentRenderer(
    workout: Workout,
    workoutComponent: WorkoutComponent,
    showRest: Boolean,
    appViewModel: AppViewModel,
    modifier: Modifier = Modifier,
    titleModifier: Modifier = Modifier
) {
    when (workoutComponent) {
        is Exercise -> {
            StyledCard(enabled = workoutComponent.enabled) {
                ExerciseRenderer(
                    modifier = modifier,
                    exercise = workoutComponent,
                    showRest = showRest,
                    appViewModel = appViewModel,
                    titleModifier = titleModifier
                )
            }
        }

        is Rest -> {
            SetRestRowCard(
                modifier = modifier.fillMaxWidth().then(titleModifier),
                enabled = workoutComponent.enabled,
                restText = "REST ${formatTime(workoutComponent.timeInSeconds)}"
            )
        }

        is Superset -> {
            val superSet = workoutComponent as Superset

            SupersetRenderer(
                superset = superSet,
                modifier = modifier,
                showRest = showRest,
                appViewModel = appViewModel,
                titleModifier = titleModifier,
                onExerciseClick = { exerciseId ->
                    appViewModel.setScreenData(
                        ScreenData.ExerciseDetail(
                            workout.id,
                            exerciseId
                        )
                    )
                }
            )
        }
    }
}

private const val TAG = "WorkoutDetailScreen"

@SuppressLint("UnusedMaterial3ScaffoldPaddingParameter")
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun WorkoutDetailScreen(
    appViewModel: AppViewModel,
    healthConnectClient: HealthConnectClient,
    workoutViewModel: WorkoutViewModel,
    workoutHistoryDao: WorkoutHistoryDao,
    workoutRecordDao: WorkoutRecordDao,
    setHistoryDao: SetHistoryDao,
    exerciseInfoDao: ExerciseInfoDao,
    workoutScheduleDao: com.gabstra.myworkoutassistant.shared.WorkoutScheduleDao,
    workout: Workout,
    initialSelectedTabIndex: Int = 0,
    initialWorkoutHistoryId: UUID? = null,
    onGoBack: () -> Unit
) {
    val context = LocalContext.current

    val isCheckingWorkoutRecord by workoutViewModel.isCheckingWorkoutRecord.collectAsState()
    val currentSelectedWorkoutId by workoutViewModel.selectedWorkoutId
    val hasWorkoutRecordFlow by workoutViewModel.hasWorkoutRecord.collectAsState()

    // Stabilize hasWorkoutRecord to prevent blink - only update when check completes
    // Use remember with workout.id as key to reset when workout changes
    var hasWorkoutRecord by remember(workout.id) { mutableStateOf(false) }

    var showDeleteDialog by remember { mutableStateOf(false) }
    var showStartConfirmationDialog by remember { mutableStateOf(false) }

    // Helper function to start workout directly (bypasses permission launcher when permissions disabled)
    val startWorkoutDirectly = {
        if (hasWorkoutRecord) workoutViewModel.deleteWorkoutRecord()
        workoutViewModel.startWorkout()
        val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
        prefs.edit { putBoolean("isWorkoutInProgress", true) }
        appViewModel.setScreenData(ScreenData.Workout(workout.id))
    }

    // Helper function to resume workout directly
    val resumeWorkoutDirectly = {
        workoutViewModel.resumeWorkoutFromRecord()
        val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
        prefs.edit { putBoolean("isWorkoutInProgress", true) }
        appViewModel.setScreenData(ScreenData.Workout(workout.id))
    }

    LaunchedEffect(workout.id) {
        // Only set if different to avoid unnecessary state updates and recompositions
        if (currentSelectedWorkoutId != workout.id) {
            workoutViewModel.setSelectedWorkoutId(workout.id)
        }
    }

    // Update hasWorkoutRecord only when check completes and workout ID matches
    // This prevents UI from updating during the async check, eliminating the blink
    LaunchedEffect(
        hasWorkoutRecordFlow,
        isCheckingWorkoutRecord,
        workout.id,
        currentSelectedWorkoutId
    ) {
        if (!isCheckingWorkoutRecord && currentSelectedWorkoutId == workout.id) {
            hasWorkoutRecord = hasWorkoutRecordFlow
        }
    }

    LaunchedEffect(hasWorkoutRecord) {
        // Fix: Clear stale isWorkoutInProgress flag if there's no workout record
        // This prevents auto-starting workouts when the flag persisted from a previous session
        if (!hasWorkoutRecord) {
            val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
            val isWorkoutInProgress = prefs.getBoolean("isWorkoutInProgress", false)
            if (isWorkoutInProgress) {
                prefs.edit { putBoolean("isWorkoutInProgress", false) }
            }
        }
    }


    var selectedComponentIds by remember { mutableStateOf(setOf<UUID>()) }
    val selectedWorkoutComponents = remember(workout.workoutComponents, selectedComponentIds) {
        workout.workoutComponents.filter { it.id in selectedComponentIds }
    }
    var isSelectionModeActive by remember { mutableStateOf(false) }
    var pendingComponentBringIntoViewId by remember { mutableStateOf<UUID?>(null) }

    var showRest by remember { mutableStateOf(true) }

    var showMoveWorkoutDialog by remember { mutableStateOf(false) }
    val allWorkouts by appViewModel.workoutsFlow.collectAsState()


    val scope = rememberCoroutineScope()
    var isSaving by remember { mutableStateOf(false) }

    fun updateWorkoutWithHistory(updatedWorkout: Workout) {
        if (isSaving) return
        isSaving = true
        scope.launch {
            try {
                val hasHistory = withContext(Dispatchers.IO) {
                    workoutHistoryDao.workoutHistoryExistsByWorkoutId(workout.id)
                }
                withContext(Dispatchers.Main) {
                    appViewModel.updateWorkoutVersioned(workout, updatedWorkout, hasHistory)
                }
                appViewModel.scheduleWorkoutSave(context)
            } finally {
                isSaving = false
            }
        }
    }

    LaunchedEffect(showRest) {
        selectedComponentIds = emptySet()
    }

    val editModeBottomBar = @Composable {
        BottomAppBar(
            contentPadding = PaddingValues(0.dp),
            containerColor = Color.Transparent,
            actions = {
                val selectionIconColors = IconButtonDefaults.iconButtonColors(
                    contentColor = MaterialTheme.colorScheme.onBackground,
                    disabledContentColor = DisabledContentGray
                )
                val scrollState = rememberScrollState()
                val canScrollForward by remember {
                    derivedStateOf { scrollState.canScrollForward }
                }
                val canScrollBackward by remember {
                    derivedStateOf { scrollState.canScrollBackward }
                }
                val density = LocalDensity.current
                
                LaunchedEffect(scrollState.value) {
                    // Trigger recomposition when scroll state changes
                }
                
                Box(modifier = Modifier.fillMaxSize()) {
                    Row(
                        modifier = Modifier
                            .fillMaxSize()
                            .horizontalScroll(scrollState),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.Top
                    ) {
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        modifier = Modifier
                            .width(56.dp)
                    ) {
                        IconButton(onClick = {
                            selectedComponentIds = emptySet()
                            isSelectionModeActive = false
                        }) {
                            Icon(
                                imageVector = Icons.Default.Close,
                                contentDescription = "Close",
                                tint = Red
                            )
                        }
                        Text(
                            "Close",
                            style = MaterialTheme.typography.labelSmall,
                            textAlign = TextAlign.Center,
                            maxLines = 2,
                            modifier = Modifier.heightIn(min = 0.dp)
                        )
                    }
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        modifier = Modifier
                            .width(56.dp)
                    ) {
                        IconButton(onClick = {
                            val filteredItems = if (!showRest) workout.workoutComponents.filter { it !is Rest } else workout.workoutComponents
                            selectedComponentIds = filteredItems.map { it.id }.toSet()
                        }) {
                            Icon(
                                imageVector = Icons.Filled.CheckBox,
                                contentDescription = "Select all",
                                tint = MaterialTheme.colorScheme.onBackground
                            )
                        }
                        Text(
                            "Select all",
                            style = MaterialTheme.typography.labelSmall,
                            textAlign = TextAlign.Center,
                            maxLines = 2,
                            modifier = Modifier.heightIn(min = 0.dp)
                        )
                    }
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        modifier = Modifier
                            .width(56.dp)
                    ) {
                        IconButton(onClick = {
                            selectedComponentIds = emptySet()
                        }) {
                            Icon(
                                imageVector = Icons.Filled.CheckBoxOutlineBlank,
                                contentDescription = "Deselect all",
                                tint = MaterialTheme.colorScheme.onBackground
                            )
                        }
                        Text(
                            "Deselect all",
                            style = MaterialTheme.typography.labelSmall,
                            textAlign = TextAlign.Center,
                            maxLines = 2,
                            modifier = Modifier.heightIn(min = 0.dp)
                        )
                    }
                    // Show move buttons only if not all selected items are Rests
                    val showMoveButtons = if (selectedWorkoutComponents.isEmpty()) {
                        false
                    } else if (selectedWorkoutComponents.size == 1) {
                        selectedWorkoutComponents.first() !is Rest
                    } else {
                        selectedWorkoutComponents.any { it !is Rest }
                    }
                    
                    // Determine if we need to show enable/disable buttons
                    val showEnableDisableButtons = selectedWorkoutComponents.isNotEmpty()
                    val needDividerBeforeEnableDisable = showEnableDisableButtons && !showMoveButtons
                    
                    // Show divider before move buttons (if shown) or before enable/disable (if no move buttons)
                    if (showMoveButtons || needDividerBeforeEnableDisable) {
                        Box(
                            modifier = Modifier.fillMaxHeight(),
                            contentAlignment = Alignment.Center
                        ) {
                            VerticalDivider(
                                modifier = Modifier.height(48.dp),
                                color = MaterialTheme.colorScheme.outlineVariant
                            )
                        }
                    }
                    
                    if (showMoveButtons) {
                        Column(
                            horizontalAlignment = Alignment.CenterHorizontally,
                            modifier = Modifier
                                .width(56.dp)
                        ) {
                            IconButton(
                                enabled = selectedWorkoutComponents.size == 1 &&
                                        workout.workoutComponents.indexOfFirst { it.id == selectedWorkoutComponents.first().id } != 0,
                                onClick = {
                                    val currentWorkoutComponents = workout.workoutComponents
                                    val selectedComponent = selectedWorkoutComponents.first()

                                    val selectedIndex =
                                        currentWorkoutComponents.indexOfFirst { it.id == selectedComponent.id }

                                    if (selectedIndex <= 0) {
                                        return@IconButton
                                    }

                                    val previousIndex = selectedIndex - 1

                                    val newWorkoutComponents =
                                        currentWorkoutComponents.toMutableList().apply {
                                            val componentToMoveToPreviousSlot = this[selectedIndex]
                                            val componentToMoveToSelectedSlot = this[previousIndex]

                                            this[selectedIndex] = componentToMoveToSelectedSlot
                                            this[previousIndex] = componentToMoveToPreviousSlot
                                        }


                                    val adjustedComponents =
                                        ensureRestSeparatedByExercises(newWorkoutComponents)
                                    val updatedWorkout =
                                        workout.copy(workoutComponents = adjustedComponents)
                                    updateWorkoutWithHistory(updatedWorkout)
                                    pendingComponentBringIntoViewId = selectedComponent.id
                                },
                                colors = selectionIconColors
                            ) {
                                Icon(
                                    imageVector = Icons.Filled.ArrowUpward,
                                    contentDescription = "Move Up",
                                )
                            }
                            Text(
                                "Move Up",
                                style = MaterialTheme.typography.labelSmall,
                                textAlign = TextAlign.Center,
                                maxLines = 2,
                                modifier = Modifier.heightIn(min = 0.dp)
                            )
                        }
                        Column(
                            horizontalAlignment = Alignment.CenterHorizontally,
                            modifier = Modifier
                                .width(56.dp)
                        ) {
                            IconButton(
                                enabled = selectedWorkoutComponents.size == 1 &&
                                        workout.workoutComponents.indexOfFirst { it.id == selectedWorkoutComponents.first().id } != workout.workoutComponents.size - 1,
                                onClick = {
                                    val currentWorkoutComponents = workout.workoutComponents
                                    val selectedComponent = selectedWorkoutComponents.first()

                                    val selectedIndex =
                                        currentWorkoutComponents.indexOfFirst { it.id == selectedComponent.id }

                                    if (selectedIndex < 0 || selectedIndex + 1 >= currentWorkoutComponents.size) {
                                        return@IconButton
                                    }

                                    val nextIndex = selectedIndex + 1

                                    val newWorkoutComponents =
                                        currentWorkoutComponents.toMutableList().apply {
                                            val componentToMoveToPreviousSlot = this[selectedIndex]
                                            val componentToMoveToSelectedSlot = this[nextIndex]

                                            this[selectedIndex] = componentToMoveToSelectedSlot
                                            this[nextIndex] = componentToMoveToPreviousSlot
                                        }

                                    val adjustedComponents =
                                        ensureRestSeparatedByExercises(newWorkoutComponents)
                                    val updatedWorkout =
                                        workout.copy(workoutComponents = adjustedComponents)
                                    updateWorkoutWithHistory(updatedWorkout)
                                    pendingComponentBringIntoViewId = selectedComponent.id
                                },
                                colors = selectionIconColors
                            ) {
                                Icon(
                                    imageVector = Icons.Filled.ArrowDownward,
                                    contentDescription = "Move Down"
                                )
                            }
                            Text(
                                "Move Down",
                                style = MaterialTheme.typography.labelSmall,
                                textAlign = TextAlign.Center,
                                maxLines = 2,
                                modifier = Modifier.heightIn(min = 0.dp)
                            )
                        }
                    }
                    // Enable/Disable logic: single selection shows one button, multi-selection shows both
                    if (selectedWorkoutComponents.size == 1) {
                        // Single selection: show one button based on current state
                        val isEnabled = getEnabledStatusOfWorkoutComponent(selectedWorkoutComponents.first())
                        if (!isEnabled) {
                            // Show Enable button
                            Column(
                                horizontalAlignment = Alignment.CenterHorizontally,
                                modifier = Modifier
                                    .width(56.dp)
                            ) {
                                IconButton(
                                    onClick = {
                                        val updatedWorkoutComponents =
                                            workout.workoutComponents.map { workoutComponent ->
                                                if (selectedWorkoutComponents.any { it.id == workoutComponent.id }) {
                                                    when (workoutComponent) {
                                                        is Exercise -> workoutComponent.copy(enabled = true)
                                                        is Rest -> workoutComponent.copy(enabled = true)
                                                        is Superset -> workoutComponent.copy(enabled = true)
                                                        else -> workoutComponent
                                                    }
                                                } else {
                                                    workoutComponent
                                                }
                                            }

                                        val adjustedComponents =
                                            ensureRestSeparatedByExercises(updatedWorkoutComponents)

                                        val updatedWorkout =
                                            workout.copy(workoutComponents = adjustedComponents)
                                        updateWorkoutWithHistory(updatedWorkout)

                                        selectedComponentIds = emptySet()
                                        isSelectionModeActive = false
                                    },
                                    colors = selectionIconColors
                                ) {
                                    Icon(
                                        imageVector = Icons.Filled.CheckCircle,
                                        contentDescription = "Enable",
                                    )
                                }
                                Text(
                                    "Enable",
                                    style = MaterialTheme.typography.labelSmall,
                                    textAlign = TextAlign.Center,
                                    maxLines = 2,
                                    modifier = Modifier.heightIn(min = 0.dp)
                                )
                            }
                        } else {
                            // Show Disable button
                            Column(
                                horizontalAlignment = Alignment.CenterHorizontally,
                                modifier = Modifier
                                    .width(56.dp)
                            ) {
                                IconButton(
                                    onClick = {
                                        val updatedWorkoutComponents =
                                            workout.workoutComponents.map { workoutComponent ->
                                                if (selectedWorkoutComponents.any { it.id == workoutComponent.id }) {
                                                    when (workoutComponent) {
                                                        is Exercise -> workoutComponent.copy(enabled = false)
                                                        is Rest -> workoutComponent.copy(enabled = false)
                                                        is Superset -> workoutComponent.copy(enabled = false)
                                                        else -> workoutComponent
                                                    }
                                                } else {
                                                    workoutComponent
                                                }
                                            }

                                        val adjustedComponents =
                                            ensureRestSeparatedByExercises(updatedWorkoutComponents)

                                        val updatedWorkout =
                                            workout.copy(workoutComponents = adjustedComponents)
                                        updateWorkoutWithHistory(updatedWorkout)
                                        selectedComponentIds = emptySet()
                                        isSelectionModeActive = false
                                    },
                                    colors = selectionIconColors
                                ) {
                                    Icon(
                                        imageVector = Icons.Filled.Block,
                                        contentDescription = "Disable",
                                    )
                                }
                                Text(
                                    "Disable",
                                    style = MaterialTheme.typography.labelSmall,
                                    textAlign = TextAlign.Center,
                                    maxLines = 2,
                                    modifier = Modifier.heightIn(min = 0.dp)
                                )
                            }
                        }
                    } else if (selectedWorkoutComponents.size > 1) {
                        // Multi-selection: show both Enable and Disable buttons
                        val hasDisabledItems = selectedWorkoutComponents.any { !getEnabledStatusOfWorkoutComponent(it) }
                        val hasEnabledItems = selectedWorkoutComponents.any { getEnabledStatusOfWorkoutComponent(it) }
                        
                        if (hasDisabledItems) {
                            Column(
                                horizontalAlignment = Alignment.CenterHorizontally,
                                modifier = Modifier
                                    .width(56.dp)
                            ) {
                                IconButton(
                                    onClick = {
                                        val updatedWorkoutComponents =
                                            workout.workoutComponents.map { workoutComponent ->
                                                if (selectedWorkoutComponents.any { it.id == workoutComponent.id }) {
                                                    when (workoutComponent) {
                                                        is Exercise -> workoutComponent.copy(enabled = true)
                                                        is Rest -> workoutComponent.copy(enabled = true)
                                                        is Superset -> workoutComponent.copy(enabled = true)
                                                        else -> workoutComponent
                                                    }
                                                } else {
                                                    workoutComponent
                                                }
                                            }

                                        val adjustedComponents =
                                            ensureRestSeparatedByExercises(updatedWorkoutComponents)

                                        val updatedWorkout =
                                            workout.copy(workoutComponents = adjustedComponents)
                                        updateWorkoutWithHistory(updatedWorkout)

                                        selectedComponentIds = emptySet()
                                        isSelectionModeActive = false
                                    },
                                    colors = selectionIconColors
                                ) {
                                    Icon(
                                        imageVector = Icons.Filled.CheckCircle,
                                        contentDescription = "Enable",
                                    )
                                }
                                Text(
                                    "Enable",
                                    style = MaterialTheme.typography.labelSmall,
                                    textAlign = TextAlign.Center,
                                    maxLines = 2,
                                    modifier = Modifier.heightIn(min = 0.dp)
                                )
                            }
                        }
                        if (hasEnabledItems) {
                            Column(
                                horizontalAlignment = Alignment.CenterHorizontally,
                                modifier = Modifier
                                    .width(56.dp)
                            ) {
                                IconButton(
                                    onClick = {
                                        val updatedWorkoutComponents =
                                            workout.workoutComponents.map { workoutComponent ->
                                                if (selectedWorkoutComponents.any { it.id == workoutComponent.id }) {
                                                    when (workoutComponent) {
                                                        is Exercise -> workoutComponent.copy(enabled = false)
                                                        is Rest -> workoutComponent.copy(enabled = false)
                                                        is Superset -> workoutComponent.copy(enabled = false)
                                                        else -> workoutComponent
                                                    }
                                                } else {
                                                    workoutComponent
                                                }
                                            }

                                        val adjustedComponents =
                                            ensureRestSeparatedByExercises(updatedWorkoutComponents)

                                        val updatedWorkout =
                                            workout.copy(workoutComponents = adjustedComponents)
                                        updateWorkoutWithHistory(updatedWorkout)
                                        selectedComponentIds = emptySet()
                                        isSelectionModeActive = false
                                    },
                                    colors = selectionIconColors
                                ) {
                                    Icon(
                                        imageVector = Icons.Filled.Block,
                                        contentDescription = "Disable",
                                    )
                                }
                                Text(
                                    "Disable",
                                    style = MaterialTheme.typography.labelSmall,
                                    textAlign = TextAlign.Center,
                                    maxLines = 2,
                                    modifier = Modifier.heightIn(min = 0.dp)
                                )
                            }
                        }
                    }

                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        modifier = Modifier
                            .width(56.dp)
                    ) {
                        IconButton(
                            enabled = selectedWorkoutComponents.isNotEmpty(),
                            onClick = {
                                val newWorkoutComponents = selectedWorkoutComponents.map {
                                    cloneWorkoutComponent(it)
                                }

                                val updatedWorkout =
                                    workout.copy(workoutComponents = workout.workoutComponents + newWorkoutComponents)
                                updateWorkoutWithHistory(updatedWorkout)
                                selectedComponentIds = emptySet()

                            },
                            colors = selectionIconColors
                        ) {
                            Icon(
                                imageVector = Icons.Default.ContentCopy,
                                contentDescription = "Copy",
                            )
                        }
                        Text(
                            "Copy",
                            style = MaterialTheme.typography.labelSmall,
                            textAlign = TextAlign.Center,
                            maxLines = 2,
                            modifier = Modifier.heightIn(min = 0.dp)
                        )
                    }
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        modifier = Modifier
                            .width(56.dp)
                    ) {
                        IconButton(
                            enabled = selectedWorkoutComponents.isNotEmpty(),
                            onClick = { showMoveWorkoutDialog = true },
                            colors = selectionIconColors
                        ) {
                            Icon(
                                imageVector = Icons.Default.MoveDown,
                                contentDescription = "Move",
                            )
                        }
                        Text(
                            "Move",
                            style = MaterialTheme.typography.labelSmall,
                            textAlign = TextAlign.Center,
                            maxLines = 2,
                            modifier = Modifier.heightIn(min = 0.dp)
                        )
                    }
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        modifier = Modifier
                            .width(56.dp)
                    ) {
                        IconButton(onClick = {
                            val superSetExercises =
                                selectedWorkoutComponents.filterIsInstance<Superset>()
                                    .flatMap { it.exercises }

                            val newWorkoutComponents = workout.workoutComponents.filter { item ->
                                selectedWorkoutComponents.none { it.id == item.id }
                            } + superSetExercises

                            val adjustedComponents =
                                ensureRestSeparatedByExercises(newWorkoutComponents)

                            val updatedWorkout =
                                workout.copy(workoutComponents = adjustedComponents)
                            val selectedExerciseIds =
                                selectedWorkoutComponents.filterIsInstance<Exercise>()
                                    .map { it.id }
                            updateWorkoutWithHistory(updatedWorkout)
                            selectedComponentIds = emptySet()
                            isSelectionModeActive = false

                            if (selectedExerciseIds.isNotEmpty()) {
                                scope.launch {
                                    withContext(Dispatchers.IO) {
                                        selectedExerciseIds.forEach {
                                            setHistoryDao.deleteByExerciseId(it)
                                            exerciseInfoDao.deleteById(it)
                                        }
                                    }
                                }
                            }
                        }) {
                            Icon(
                                imageVector = Icons.Default.Delete,
                                contentDescription = "Delete",
                                tint = MaterialTheme.colorScheme.onBackground
                            )
                        }
                        Text(
                            "Delete",
                            style = MaterialTheme.typography.labelSmall,
                            textAlign = TextAlign.Center,
                            maxLines = 2,
                            modifier = Modifier.heightIn(min = 0.dp)
                        )
                    }
                    }
                    
                    // Right side chevron
                    if (canScrollForward) {
                        Box(
                            modifier = Modifier
                                .fillMaxHeight()
                                .background(
                                    brush = Brush.horizontalGradient(
                                        colors = listOf(Color.Transparent, Color.Black),
                                        startX = 0f,
                                        endX = with(density) { 32.dp.toPx() }
                                    )
                                )
                                .padding(horizontal = 4.dp)
                                .align(Alignment.CenterEnd),
                            contentAlignment = Alignment.Center
                        ) {
                            Icon(
                                imageVector = Icons.Filled.ChevronRight,
                                contentDescription = "Scroll right",
                                tint = MaterialTheme.colorScheme.onBackground
                            )
                        }
                    }
                    
                    // Left side chevron
                    if (canScrollBackward) {
                        Box(
                            modifier = Modifier
                                .fillMaxHeight()
                                .background(
                                    brush = Brush.horizontalGradient(
                                        colors = listOf(Color.Black, Color.Transparent),
                                        startX = 0f,
                                        endX = with(density) { 32.dp.toPx() }
                                    )
                                )
                                .padding(horizontal = 4.dp)
                                .align(Alignment.CenterStart),
                            contentAlignment = Alignment.Center
                        ) {
                            Icon(
                                imageVector = Icons.Filled.ChevronLeft,
                                contentDescription = "Scroll left",
                                tint = MaterialTheme.colorScheme.onBackground
                            )
                        }
                    }
                }
            }
        )
    }


    Box(modifier = Modifier.fillMaxSize()) {
        Scaffold(
            topBar = {
                TopAppBar(
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = MaterialTheme.colorScheme.background,
                        titleContentColor = MaterialTheme.colorScheme.onBackground,
                        navigationIconContentColor = MaterialTheme.colorScheme.onBackground,
                        actionIconContentColor = MaterialTheme.colorScheme.onBackground
                    ),
                    title = {
                        Text(
                            modifier = Modifier
                                .fillMaxWidth()
                                .basicMarquee(),
                            textAlign = TextAlign.Center,
                            text = workout.name,
                            maxLines = 2,
                            style = MaterialTheme.typography.titleLarge,
                            color = MaterialTheme.colorScheme.onBackground
                        )
                    },
                    navigationIcon = {
                        IconButton(onClick = onGoBack) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                contentDescription = "Back"
                            )
                        }
                    },
                    actions = {
                        Menu(
                            onEditWorkout = {
                                appViewModel.setScreenData(ScreenData.EditWorkout(workout.id));
                            },
                            onClearHistory = {
                                scope.launch {
                                    withContext(Dispatchers.Main) {
                                        workoutHistoryDao.deleteAllByWorkoutId(workout.id)
                                        workoutRecordDao.deleteByWorkoutId(workout.id)
                                        Toast.makeText(
                                            context,
                                            "History deleted",
                                            Toast.LENGTH_SHORT
                                        ).show()
                                    }
                                }
                            }
                        )
                    }
                )
            },
            bottomBar = {
                if (isSelectionModeActive) {
                    Column {
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        editModeBottomBar()
                    }
                }
            },
        ) { paddingValues ->
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .background(MaterialTheme.colorScheme.background)
                    .padding(paddingValues),
                verticalArrangement = Arrangement.Top,
            ) {
                var selectedTopTab by remember(workout.id, initialSelectedTabIndex) {
                    mutableIntStateOf(initialSelectedTabIndex.coerceIn(0, 1))
                }
                SwipeableTabs(
                    tabTitles = listOf("Overview", "History"),
                    selectedTabIndex = selectedTopTab,
                    onTabSelected = { index ->
                        selectedTopTab = index
                    },
                    modifier = Modifier.fillMaxSize(),
                    pagerModifier = Modifier.fillMaxSize()
                ) { pageIndex ->
                    when (pageIndex) {
                        0 -> WorkoutOverviewTab(
                            appViewModel = appViewModel,
                            workout = workout,
                            hasWorkoutRecord = hasWorkoutRecord,
                            isCheckingWorkoutRecord = isCheckingWorkoutRecord,
                            currentSelectedWorkoutId = currentSelectedWorkoutId,
                            showRest = showRest,
                            onShowRestChange = { showRest = it },
                            selectedWorkoutComponents = selectedWorkoutComponents,
                            isSelectionModeActive = isSelectionModeActive,
                            onEnableSelection = { isSelectionModeActive = true },
                            onDisableSelection = { isSelectionModeActive = false },
                            onSelectedComponentIdsChange = { selectedComponentIds = it },
                            pendingComponentBringIntoViewId = pendingComponentBringIntoViewId,
                            onPendingComponentBringIntoViewConsumed = {
                                pendingComponentBringIntoViewId = null
                            },
                            onRequestStartWorkout = {
                                if (hasWorkoutRecord) {
                                    showStartConfirmationDialog = true
                                } else {
                                    startWorkoutDirectly()
                                }
                            },
                            onResumeWorkout = { resumeWorkoutDirectly() },
                            onRequestDeleteInterruptedWorkout = { showDeleteDialog = true },
                            onWorkoutComponentsReordered = { adjustedComponents ->
                                val updatedWorkout = workout.copy(workoutComponents = adjustedComponents)
                                updateWorkoutWithHistory(updatedWorkout)
                            },
                            workoutScheduleDao = workoutScheduleDao
                        )
                        1 -> WorkoutHistoryTab(
                            appViewModel = appViewModel,
                            healthConnectClient = healthConnectClient,
                            workoutHistoryDao = workoutHistoryDao,
                            workoutRecordDao = workoutRecordDao,
                            workoutHistoryId = initialWorkoutHistoryId,
                            setHistoryDao = setHistoryDao,
                            workout = workout,
                            onGoBack = onGoBack,
                            onNavigateToOverview = { selectedTopTab = 0 }
                        )
                    }
                }


                MoveExercisesToWorkoutDialog(
                    show = showMoveWorkoutDialog,
                    onDismiss = { showMoveWorkoutDialog = false },
                    workouts = allWorkouts,
                    currentWorkout = workout,
                    onMove = { targetWorkout ->
                        scope.launch {
                            val (sourceHasHistory, targetHasHistory) = withContext(Dispatchers.IO) {
                                workoutHistoryDao.workoutHistoryExistsByWorkoutId(workout.id) to
                                        workoutHistoryDao.workoutHistoryExistsByWorkoutId(
                                            targetWorkout.id
                                        )
                            }
                            withContext(Dispatchers.Main) {
                                appViewModel.moveComponentsVersioned(
                                    workout,
                                    selectedWorkoutComponents,
                                    targetWorkout,
                                    sourceHasHistory,
                                    targetHasHistory
                                )

                                selectedComponentIds = emptySet()
                                isSelectionModeActive = false
                                Toast.makeText(
                                    context,
                                    "Selection moved to ${targetWorkout.name}",
                                    Toast.LENGTH_SHORT
                                ).show()

                                appViewModel.setScreenData(ScreenData.WorkoutDetail(targetWorkout.id))
                            }
                        }
                    }
                )
            }

            CustomDialogYesOnLongPress(
                show = showDeleteDialog,
                title = InterruptedWorkoutCopy.DELETE_TITLE,
                message = InterruptedWorkoutCopy.DELETE_MESSAGE,
                handleYesClick = {
                    workoutViewModel.deleteWorkoutRecord()
                    showDeleteDialog = false
                },
                handleNoClick = {
                    showDeleteDialog = false
                },
                closeTimerInMillis = 5000,
                handleOnAutomaticClose = {
                    showDeleteDialog = false
                }
            )

            CustomDialogYesOnLongPress(
                show = showStartConfirmationDialog,
                title = "Start New Workout",
                message = InterruptedWorkoutCopy.START_NEW_WORKOUT_MESSAGE,
                handleYesClick = {
                    showStartConfirmationDialog = false
                    startWorkoutDirectly()
                },
                handleNoClick = {
                    showStartConfirmationDialog = false
                },
                closeTimerInMillis = 5000,
                handleOnAutomaticClose = {
                    showStartConfirmationDialog = false
                }
            )
            LoadingOverlay(isVisible = rememberDebouncedSavingVisible(isSaving), text = "Saving...")
        }
    }
}



