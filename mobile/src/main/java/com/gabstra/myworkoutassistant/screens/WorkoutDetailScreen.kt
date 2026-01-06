package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import android.content.Context
import android.widget.Toast
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.Interaction
import androidx.compose.foundation.interaction.MutableInteractionSource
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
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.TabRowDefaults
import androidx.compose.material3.TabRowDefaults.tabIndicatorOffset
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.VerticalDivider
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.edit
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.ActiveScheduleCard
import com.gabstra.myworkoutassistant.composables.AppDropdownMenu
import com.gabstra.myworkoutassistant.composables.AppDropdownMenuItem
import com.gabstra.myworkoutassistant.composables.ExerciseRenderer
import com.gabstra.myworkoutassistant.composables.GenericButtonWithMenu
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.MenuItem
import com.gabstra.myworkoutassistant.composables.MoveExercisesToWorkoutDialog
import com.gabstra.myworkoutassistant.composables.LoadingOverlay
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.composables.SupersetRenderer
import com.gabstra.myworkoutassistant.ensureRestSeparatedByExercises
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.getEnabledStatusOfWorkoutComponent
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
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
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import com.gabstra.myworkoutassistant.workout.CustomDialogYesOnLongPress
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

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
                text = { Text("Edit Workout") },
                onClick = {
                    onEditWorkout()
                    expanded = false
                }
            )
            AppDropdownMenuItem(
                text = { Text("Clear History") },
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
    appViewModel: AppViewModel
) {
    when (workoutComponent) {
        is Exercise -> {
            StyledCard(enabled = workoutComponent.enabled) {
                ExerciseRenderer(
                    exercise = workoutComponent,
                    showRest = showRest,
                    appViewModel = appViewModel
                )
            }
        }

        is Rest -> {
            val allRests = workout.workoutComponents.filterIsInstance<Rest>()
            val restIndex = allRests.indexOf(workoutComponent)
            val restCount = allRests.size
            val restText = if (restCount > 1) {
                "REST ${restIndex + 1} of $restCount - ${formatTime(workoutComponent.timeInSeconds)}"
            } else {
                "REST ${formatTime(workoutComponent.timeInSeconds)}"
            }
            
            Surface(
                modifier = Modifier.fillMaxWidth(),
                shape = RectangleShape,
                color = if (workoutComponent.enabled) {
                    MaterialTheme.colorScheme.surfaceVariant
                } else {
                    MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f)
                }
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    val restColor = if (workoutComponent.enabled) {
                        MaterialTheme.colorScheme.onBackground
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    }
                    Text(
                        text = restText,
                        style = MaterialTheme.typography.bodyMedium,
                        color = restColor,
                        textAlign = TextAlign.Center
                    )
                }
            }
        }

        is Superset -> {
            val superSet = workoutComponent as Superset

            SupersetRenderer(
                superset = superSet,
                showRest = showRest,
                appViewModel = appViewModel,
                workoutId = workout.id,
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

@SuppressLint("UnusedMaterial3ScaffoldPaddingParameter")
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun WorkoutDetailScreen(
    appViewModel: AppViewModel,
    workoutViewModel: WorkoutViewModel,
    workoutHistoryDao: WorkoutHistoryDao,
    workoutRecordDao: WorkoutRecordDao,
    setHistoryDao: SetHistoryDao,
    exerciseInfoDao: ExerciseInfoDao,
    workoutScheduleDao: com.gabstra.myworkoutassistant.shared.WorkoutScheduleDao,
    workout: Workout,
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


    var selectedWorkoutComponents by remember { mutableStateOf(listOf<WorkoutComponent>()) }
    var isSelectionModeActive by remember { mutableStateOf(false) }

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
                com.gabstra.myworkoutassistant.saveWorkoutStoreWithBackupFromContext(
                    context,
                    appViewModel.workoutStore
                )
            } finally {
                isSaving = false
            }
        }
    }

    LaunchedEffect(showRest) {
        selectedWorkoutComponents = emptyList()
    }

    LaunchedEffect(workout.workoutComponents) {
        // Sync selectedWorkoutComponents with new component references when workout updates
        if (selectedWorkoutComponents.isNotEmpty()) {
            val selectedIds = selectedWorkoutComponents.map { it.id }.toSet()
            selectedWorkoutComponents = workout.workoutComponents.filter { it.id in selectedIds }
        }
    }

    val editModeBottomBar = @Composable {
        BottomAppBar(
            contentPadding = PaddingValues(0.dp),
            containerColor = Color.Transparent,
            actions = {
                val selectionIconColors = IconButtonDefaults.iconButtonColors(
                    contentColor = MaterialTheme.colorScheme.onBackground,
                    disabledContentColor = MaterialTheme.colorScheme.onSurfaceVariant
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
                            selectedWorkoutComponents = emptyList()
                            isSelectionModeActive = false
                        }) {
                            Icon(
                                imageVector = Icons.Default.Close,
                                contentDescription = "Cancel selection",
                                tint = MaterialTheme.colorScheme.onBackground
                            )
                        }
                        Text(
                            "Cancel selection",
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
                            selectedWorkoutComponents = filteredItems
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
                            selectedWorkoutComponents = emptyList()
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
                    Box(
                        modifier = Modifier.fillMaxHeight(),
                        contentAlignment = Alignment.Center
                    ) {
                        VerticalDivider(
                            modifier = Modifier.height(48.dp),
                            color = MaterialTheme.colorScheme.outlineVariant
                        )
                    }
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        modifier = Modifier
                            .width(56.dp)
                    ) {
                        IconButton(
                            enabled = selectedWorkoutComponents.size == 1 &&
                                    workout.workoutComponents.indexOfFirst { it.id == selectedWorkoutComponents.first().id } != 0 &&
                                    selectedWorkoutComponents.first() !is Rest,
                            onClick = {
                                val currentWorkoutComponents = workout.workoutComponents
                                val selectedComponent = selectedWorkoutComponents.first()

                                val selectedIndex =
                                    currentWorkoutComponents.indexOfFirst { it.id == selectedComponent.id }

                                if (selectedIndex <= 0) {
                                    return@IconButton
                                }

                                val previousWorkoutComponent =
                                    currentWorkoutComponents.subList(0, selectedIndex)
                                        .lastOrNull { it !is Rest }

                                if (previousWorkoutComponent == null) {
                                    return@IconButton
                                }

                                val previousIndex =
                                    currentWorkoutComponents.indexOfFirst { it.id == previousWorkoutComponent.id }

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
                                    workout.workoutComponents.indexOfFirst { it.id == selectedWorkoutComponents.first().id } != workout.workoutComponents.size - 1 &&
                                    selectedWorkoutComponents.first() !is Rest,
                            onClick = {
                                val currentWorkoutComponents = workout.workoutComponents
                                val selectedComponent = selectedWorkoutComponents.first()

                                val selectedIndex =
                                    currentWorkoutComponents.indexOfFirst { it.id == selectedComponent.id }

                                if (selectedIndex < 0 || selectedIndex + 1 >= currentWorkoutComponents.size) {
                                    return@IconButton
                                }

                                val nextWorkoutComponent = currentWorkoutComponents.subList(
                                    selectedIndex + 1,
                                    currentWorkoutComponents.size
                                )
                                    .firstOrNull { it !is Rest }

                                if (nextWorkoutComponent == null) {
                                    return@IconButton
                                }

                                val nextIndex =
                                    currentWorkoutComponents.indexOfFirst { it.id == nextWorkoutComponent.id }

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
                    if (selectedWorkoutComponents.any { !getEnabledStatusOfWorkoutComponent(it) }) {
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

                                    selectedWorkoutComponents = emptyList()
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
                                    selectedWorkoutComponents = emptyList()
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
                                selectedWorkoutComponents = emptyList()

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
                            updateWorkoutWithHistory(updatedWorkout)
                            selectedWorkoutComponents = emptyList()
                            isSelectionModeActive = false

                            val selectedExerciseIds =
                                selectedWorkoutComponents.toList().filterIsInstance<Exercise>()
                                    .map { it.id }
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
                            text = workout.name
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
                if (selectedWorkoutComponents.isNotEmpty()) {
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
                TabRow(
                    modifier = Modifier.fillMaxWidth(),
                    containerColor = MaterialTheme.colorScheme.background,
                    contentColor = MaterialTheme.colorScheme.onBackground,
                    selectedTabIndex = 0,
                    indicator = { tabPositions ->
                        TabRowDefaults.Indicator(
                            Modifier.tabIndicatorOffset(tabPositions[0]),
                            color = MaterialTheme.colorScheme.primary,
                            height = 2.dp // Set the indicator thickness
                        )
                    }
                ) {
                    Tab(
                        modifier = Modifier.background(MaterialTheme.colorScheme.background),
                        selected = true,
                        onClick = { },
                        text = {
                            Text(
                                text = "Overview"
                            )
                        },
                        selectedContentColor = MaterialTheme.colorScheme.primary,
                        unselectedContentColor = MaterialTheme.colorScheme.onBackground,
                        interactionSource = object : MutableInteractionSource {
                            override val interactions: Flow<Interaction> = emptyFlow()

                            override suspend fun emit(interaction: Interaction) {
                                // Empty implementation
                            }

                            override fun tryEmit(interaction: Interaction): Boolean = true
                        }
                    )
                    Tab(
                        modifier = Modifier.background(MaterialTheme.colorScheme.background),
                        selected = false,
                        onClick = {
                            appViewModel.setScreenData(
                                ScreenData.WorkoutHistory(workout.id),
                                true
                            )
                        },
                        text = {
                            Text(

                                text = "History"
                            )
                        },
                        selectedContentColor = MaterialTheme.colorScheme.primary,
                        unselectedContentColor = MaterialTheme.colorScheme.onBackground,
                        interactionSource = object : MutableInteractionSource {
                            override val interactions: Flow<Interaction> = emptyFlow()

                            override suspend fun emit(interaction: Interaction) {
                                // Empty implementation
                            }

                            override fun tryEmit(interaction: Interaction): Boolean = true
                        }
                    )
                }

                val scrollState = rememberScrollState()

                Column(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth()
                        .padding(top = 10.dp)
                        .padding(bottom = 10.dp)
                        .verticalColumnScrollbar(scrollState)
                        .verticalScroll(scrollState)
                        .padding(horizontal = 15.dp),
                ) {
                    if (workout.workoutComponents.isEmpty()) {
                        Row(
                            modifier = Modifier
                                .fillMaxSize()
                                .padding(5.dp),
                            horizontalArrangement = Arrangement.Center, // Space items evenly, including space at the edges
                            verticalAlignment = Alignment.CenterVertically // Center items vertically within the Row
                        ) {
                            GenericButtonWithMenu(
                                menuItems = listOf(
                                    MenuItem("Add Exercise") {
                                        appViewModel.setScreenData(
                                            ScreenData.NewExercise(
                                                workout.id
                                            )
                                        );
                                    },
                                    MenuItem("Add Superset") {
                                        appViewModel.setScreenData(
                                            ScreenData.NewSuperset(
                                                workout.id
                                            )
                                        );
                                    }
                                ),
                                content = {
                                    Text(
                                        "Add Workout Component",
                                        color = MaterialTheme.colorScheme.background
                                    )
                                }
                            )
                        }
                    } else {
                        if (workout.enabled) {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.Center
                            ) {
                                Button(
                                    onClick = {
                                        if (hasWorkoutRecord) {
                                            showStartConfirmationDialog = true
                                        } else {
                                            startWorkoutDirectly()
                                        }
                                    },
                                ) {
                                    Text(
                                        text = "Start Workout",
                                        textAlign = TextAlign.Center,
                                        style = MaterialTheme.typography.bodyLarge,
                                        color = MaterialTheme.colorScheme.background
                                    )
                                }
                            }

                            // Only show resume/delete buttons after check completes and if there's a workout record
                            if (!isCheckingWorkoutRecord && currentSelectedWorkoutId == workout.id && hasWorkoutRecord) {
                                Spacer(Modifier.height(Spacing.sm))
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth(),
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.Center
                                ) {
                                    Button(
                                        onClick = {
                                            resumeWorkoutDirectly()
                                        },
                                    ) {
                                        Text(
                                            text = "Resume",
                                            textAlign = TextAlign.Center,
                                            style = MaterialTheme.typography.bodyLarge,
                                            color = MaterialTheme.colorScheme.background
                                        )
                                    }
                                }
                                Spacer(Modifier.height(Spacing.sm))
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth(),
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.Center
                                ) {
                                    Button(
                                        onClick = {
                                            showDeleteDialog = true
                                        },
                                    ) {
                                        Text(
                                            text = "Delete paused workout",
                                            textAlign = TextAlign.Center,
                                            style = MaterialTheme.typography.bodyLarge,
                                            color = MaterialTheme.colorScheme.background
                                        )
                                    }
                                }
                            }

                            Spacer(Modifier.height(Spacing.md))
                            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        }

                        // Display schedules for this workout
                        var workoutSchedules by remember {
                            mutableStateOf<List<WorkoutSchedule>>(
                                emptyList()
                            )
                        }

                        LaunchedEffect(workout.globalId) {
                            withContext(Dispatchers.IO) {
                                workoutSchedules =
                                    workoutScheduleDao.getSchedulesByWorkoutId(workout.globalId)
                            }
                        }

                        if (workoutSchedules.isNotEmpty()) {
                            Spacer(Modifier.height(Spacing.md))
                            StyledCard {
                                Column(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(15.dp),
                                    verticalArrangement = Arrangement.spacedBy(10.dp)
                                ) {
                                    Text(
                                        text = "Workout Schedules",
                                        style = MaterialTheme.typography.titleMedium,
                                        color = MaterialTheme.colorScheme.onBackground
                                    )

                                    workoutSchedules.forEachIndexed { index, schedule ->
                                        ActiveScheduleCard(
                                            schedule = schedule,
                                            index = index,
                                            workout = workout
                                        )
                                        if (index < workoutSchedules.size - 1) {
                                            HorizontalDivider(
                                                color = MaterialTheme.colorScheme.outlineVariant,
                                                modifier = Modifier.padding(vertical = 5.dp)
                                            )
                                        }
                                    }
                                }
                            }
                            Spacer(Modifier.height(Spacing.md))
                            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        }


                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.End,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 20.dp)
                        ) {
                            Row(
                                modifier = Modifier.padding(vertical = 15.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(15.dp)
                            ) {
                                Checkbox(
                                    modifier = Modifier.size(10.dp),
                                    checked = showRest,
                                    onCheckedChange = { showRest = it },
                                    colors = CheckboxDefaults.colors().copy(
                                        checkedCheckmarkColor = MaterialTheme.colorScheme.onPrimary,
                                        uncheckedBorderColor = MaterialTheme.colorScheme.primary
                                    )
                                )
                                Text(
                                    text = "Show Rests",
                                    style = MaterialTheme.typography.bodyMedium
                                )
                            }
                        }

                        GenericSelectableList(
                            it = null,
                            items = if (!showRest) workout.workoutComponents.filter { it !is Rest } else workout.workoutComponents,
                            selectedItems = selectedWorkoutComponents,
                            isSelectionModeActive,
                            onItemClick = {
                                when (it) {
                                    is Exercise -> {
                                        appViewModel.setScreenData(
                                            ScreenData.ExerciseDetail(
                                                workout.id,
                                                it.id
                                            )
                                        )
                                    }

                                    is Rest -> {
                                        appViewModel.setScreenData(
                                            ScreenData.EditRest(
                                                workout.id,
                                                it
                                            )
                                        )
                                    }

                                    is Superset -> {
                                        appViewModel.setScreenData(
                                            ScreenData.EditSuperset(
                                                workout.id,
                                                it.id
                                            )
                                        )
                                    }

                                    else -> {}
                                }
                            },
                            onEnableSelection = { isSelectionModeActive = true },
                            onDisableSelection = { isSelectionModeActive = false },
                            onSelectionChange = { newSelection ->
                                selectedWorkoutComponents = newSelection
                            },
                            onOrderChange = { newWorkoutComponents ->
                                if (!showRest) return@GenericSelectableList

                                val adjustedComponents =
                                    ensureRestSeparatedByExercises(newWorkoutComponents)
                                val updatedWorkout =
                                    workout.copy(workoutComponents = adjustedComponents)
                                updateWorkoutWithHistory(updatedWorkout)
                            },
                            itemContent = { it ->
                                WorkoutComponentRenderer(
                                    workout = workout,
                                    workoutComponent = it,
                                    showRest = showRest,
                                    appViewModel = appViewModel
                                )
                            },
                            isDragDisabled = true,
                            keySelector = { component -> component.id }
                        )
                        GenericButtonWithMenu(
                            menuItems = listOf(
                                MenuItem("Add Exercise") {
                                    appViewModel.setScreenData(
                                        ScreenData.NewExercise(
                                            workout.id
                                        )
                                    );
                                },
                                MenuItem("Add Rests Between Exercises") {
                                    appViewModel.setScreenData(
                                        ScreenData.NewRest(
                                            workout.id,
                                            null
                                        )
                                    );
                                },
                                MenuItem("Add Superset") {
                                    appViewModel.setScreenData(
                                        ScreenData.NewSuperset(
                                            workout.id
                                        )
                                    );
                                }
                            ),
                            content = {
                                Icon(
                                    imageVector = Icons.Filled.Add,
                                    contentDescription = "Add",
                                    tint = MaterialTheme.colorScheme.background,
                                )
                            }
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

                                selectedWorkoutComponents = emptyList()
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
                title = "Delete Paused Workout",
                message = "Are you sure you want to delete this paused workout?",
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
                message = "An existing paused workout will be deleted. Continue?",
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
            LoadingOverlay(isVisible = isSaving, text = "Saving...")
        }
    }
}


