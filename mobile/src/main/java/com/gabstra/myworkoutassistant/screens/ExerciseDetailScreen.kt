package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
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
import androidx.compose.material.icons.filled.CheckBox
import androidx.compose.material.icons.filled.CheckBoxOutlineBlank
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.MoreVert
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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.AppDropdownMenu
import com.gabstra.myworkoutassistant.composables.AppDropdownMenuItem
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.composables.AppPrimaryOutlinedButton
import com.gabstra.myworkoutassistant.composables.GenericButtonWithMenu
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.LoadingOverlay
import com.gabstra.myworkoutassistant.composables.MenuItem
import com.gabstra.myworkoutassistant.composables.SetRestRowCard
import com.gabstra.myworkoutassistant.composables.SwipeableTabs
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.composables.rememberDebouncedSavingVisible
import com.gabstra.myworkoutassistant.ensureRestSeparatedBySets
import com.gabstra.myworkoutassistant.exportExerciseHistoryToMarkdown
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.CalibrationHelper
import com.gabstra.myworkoutassistant.shared.workout.calibration.CalibrationUiLabels
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.verticalColumnScrollbarContainer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.UUID

@Composable
private fun ExerciseDetailMenu(
    onEditExercise: () -> Unit,
    onExportExerciseHistory: () -> Unit,
    isExportEnabled: Boolean
) {
    var expanded by remember { mutableStateOf(false) }

    Box(modifier = Modifier.wrapContentSize(Alignment.TopEnd)) {
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
                text = { Text(text = "Edit Exercise", fontWeight = FontWeight.Normal) },
                onClick = {
                    onEditExercise()
                    expanded = false
                }
            )
            HorizontalDivider(
                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f)
            )
            AppDropdownMenuItem(
                text = { Text(text = "Export as .md", fontWeight = FontWeight.Normal) },
                enabled = isExportEnabled,
                onClick = {
                    onExportExerciseHistory()
                    expanded = false
                }
            )
        }
    }
}

@Composable
fun ComponentRenderer(
    set: Set,
    appViewModel: AppViewModel,
    exercise: Exercise,
    modifier: Modifier = Modifier
) {
    // Observe equipmentsFlow to fix race condition - recompose when equipments are loaded
    val equipments by appViewModel.equipmentsFlow.collectAsState()

    when (set) {
        is WeightSet -> {
            val equipment = exercise.equipmentId?.let { appViewModel.getEquipmentById(it) }
            val isCalibrationManagedWorkSet = CalibrationHelper.isCalibrationManagedWorkSet(
                exercise = exercise,
                set = set
            )

            StyledCard(modifier = modifier, enabled = exercise.enabled) {
                Column(
                    modifier = Modifier.padding(15.dp)
                ) {
                    Row(
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            if (!isCalibrationManagedWorkSet) {
                                Text(
                                    text = if (equipment != null) {
                                        "Weight (KG): ${equipment.formatWeight(set.weight)}"
                                    } else {
                                        "Weight (KG): ${set.weight}"
                                    },
                                    color = MaterialTheme.colorScheme.onBackground,
                                    style = MaterialTheme.typography.bodyMedium,
                                )
                            } else {
                                Text(
                                    text = CalibrationUiLabels.Tbd,
                                    color = MaterialTheme.colorScheme.onBackground,
                                    style = MaterialTheme.typography.bodyMedium
                                )
                            }
                            Text(
                                text = "Reps: ${set.reps}",
                                color = MaterialTheme.colorScheme.onBackground,
                                style = MaterialTheme.typography.bodyMedium,
                                textAlign = TextAlign.End
                            )
                        }
                    }
                }
            }

        }

        is BodyWeightSet -> {
            val equipment = exercise.equipmentId?.let { appViewModel.getEquipmentById(it) }
            val isCalibrationManagedWorkSet = CalibrationHelper.isCalibrationManagedWorkSet(
                exercise = exercise,
                set = set
            )

            StyledCard(modifier = modifier, enabled = exercise.enabled) {
                Column(
                    modifier = Modifier.padding(15.dp)
                ) {
                    Row(
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            if (!isCalibrationManagedWorkSet) {
                                if(set.additionalWeight != 0.0 && equipment != null) {
                                    Text(
                                        text = "Weight (KG): ${equipment.formatWeight(set.additionalWeight)}",
                                        color = MaterialTheme.colorScheme.onBackground,
                                        style = MaterialTheme.typography.bodyMedium,
                                    )
                                }
                            } else {
                                Text(
                                    text = CalibrationUiLabels.Tbd,
                                    color = MaterialTheme.colorScheme.onBackground,
                                    style = MaterialTheme.typography.bodyMedium
                                )
                            }
                            Text(
                                text = "Reps: ${set.reps}",
                                color = MaterialTheme.colorScheme.onBackground,
                                style = MaterialTheme.typography.bodyMedium,
                                textAlign = TextAlign.End
                            )
                        }
                    }
                }
            }

        }

        is EnduranceSet -> {
            StyledCard(modifier = modifier, enabled = exercise.enabled) {
                Row(
                    modifier = Modifier.padding(15.dp),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        modifier = Modifier.weight(1f),
                        text = formatTime(set.timeInMillis / 1000),
                        textAlign = TextAlign.Center,
                        color = MaterialTheme.colorScheme.onBackground,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }

        }

        is TimedDurationSet -> {
            StyledCard(modifier = modifier, enabled = exercise.enabled) {
                Row(
                    modifier = Modifier.padding(15.dp),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        modifier = Modifier.weight(1f),
                        text = formatTime(set.timeInMillis / 1000),
                        textAlign = TextAlign.Center,
                        color = MaterialTheme.colorScheme.onBackground,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }


        }

        is RestSet -> {
            SetRestRowCard(
                modifier = modifier.fillMaxWidth(),
                enabled = exercise.enabled,
                restText = "REST ${formatTime(set.timeInSeconds)}"
            )
        }

    }
}

@SuppressLint("UnusedMaterial3ScaffoldPaddingParameter")
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun ExerciseDetailScreen(
    appViewModel: AppViewModel,
    workout: Workout,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    exercise: Exercise,
    initialSelectedTabIndex: Int = 0,
    initialHistoryMode: Int = 0,
    onGoBack: () -> Unit
) {
    val sets = remember(exercise.sets) { ensureRestSeparatedBySets(exercise.sets) }
    var selectedSetIds by remember { mutableStateOf(setOf<UUID>()) }
    val selectedSets = remember(sets, selectedSetIds) {
        sets.filter { it.id in selectedSetIds }
    }

    var isSelectionModeActive by remember { mutableStateOf(false) }
    var showRest by remember { mutableStateOf(true) }
    var pendingSetBringIntoViewId by remember { mutableStateOf<UUID?>(null) }

    val equipments by appViewModel.equipmentsFlow.collectAsState()
    val selectedEquipmentId = exercise?.equipmentId
    val workouts by appViewModel.workoutsFlow.collectAsState()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var isSaving by remember { mutableStateOf(false) }

    fun updateExerciseWithHistory(updatedExercise: Exercise) {
        if (isSaving) return
        isSaving = true
        scope.launch {
            try {
                val hasHistory = withContext(Dispatchers.IO) {
                    workoutHistoryDao.workoutHistoryExistsByWorkoutId(workout.id)
                }
                withContext(Dispatchers.Main) {
                    appViewModel.updateWorkoutComponentVersioned(
                        workout,
                        exercise,
                        updatedExercise,
                        hasHistory
                    )
                }
                appViewModel.scheduleWorkoutSave(context)
            } finally {
                isSaving = false
            }
        }
    }

    fun exportExerciseHistory() {
        scope.launch {
            withContext(Dispatchers.IO) {
                val db = AppDatabase.getDatabase(context)
                val exerciseSessionProgressionDao = db.exerciseSessionProgressionDao()
                exportExerciseHistoryToMarkdown(
                    context = context,
                    exercise = exercise,
                    workoutHistoryDao = workoutHistoryDao,
                    setHistoryDao = setHistoryDao,
                    exerciseSessionProgressionDao = exerciseSessionProgressionDao,
                    workouts = workouts,
                    workoutStore = appViewModel.workoutStore
                )
            }
        }
    }

    LaunchedEffect(showRest) {
        selectedSetIds = emptySet()
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
                            text = exercise.name,
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
                        ExerciseDetailMenu(
                            onEditExercise = {
                                appViewModel.setScreenData(
                                    ScreenData.EditExercise(
                                        workout.id,
                                        exercise.id
                                    )
                                )
                            },
                            onExportExerciseHistory = { exportExerciseHistory() },
                            isExportEnabled = !exercise.doNotStoreHistory
                        )
                    }
                )
            },
            bottomBar = {
                if (isSelectionModeActive) {
                    Column {
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        BottomAppBar(
                            contentPadding = PaddingValues(0.dp),
                            containerColor = Color.Transparent,
                            actions = {
                                val selectionIconColors = IconButtonDefaults.iconButtonColors(
                                    contentColor = MaterialTheme.colorScheme.onBackground,
                                    disabledContentColor = DisabledContentGray
                                )
                                val scrollState = rememberScrollState()
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
                                            selectedSetIds = emptySet()
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
                                            textAlign = TextAlign.Center
                                        )
                                    }
                                    Column(
                                        horizontalAlignment = Alignment.CenterHorizontally,
                                        modifier = Modifier
                                            .width(56.dp)
                                    ) {
                                        IconButton(onClick = {
                                            val filteredSets =
                                                if (!showRest) sets.filter { it !is RestSet } else sets
                                            selectedSetIds = filteredSets.map { it.id }.toSet()
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
                                            textAlign = TextAlign.Center
                                        )
                                    }
                                    Column(
                                        horizontalAlignment = Alignment.CenterHorizontally,
                                        modifier = Modifier
                                            .width(56.dp)
                                    ) {
                                        IconButton(onClick = {
                                            selectedSetIds = emptySet()
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
                                            textAlign = TextAlign.Center
                                        )
                                    }
                                    // Show move buttons only if not all selected items are RestSets
                                    val showMoveButtons = if (selectedSets.isEmpty()) {
                                        false
                                    } else if (selectedSets.size == 1) {
                                        selectedSets.first() !is RestSet
                                    } else {
                                        selectedSets.any { it !is RestSet }
                                    }

                                    if (showMoveButtons) {
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
                                                enabled = selectedSets.size == 1 &&
                                                        exercise.sets.indexOfFirst { it.id == selectedSets.first().id } != 0,
                                                onClick = {
                                                    val currentSets = exercise.sets
                                                    val selectedComponent = selectedSets.first()

                                                    val selectedIndex =
                                                        currentSets.indexOfFirst { it.id == selectedComponent.id }

                                                    if (selectedIndex <= 0) {
                                                        return@IconButton
                                                    }

                                                    val previousIndex = selectedIndex - 1

                                                    val newSets =
                                                        currentSets.toMutableList().apply {
                                                            val componentToMoveToOtherSlot =
                                                                this[selectedIndex]
                                                            val componentToMoveToSelectedSlot =
                                                                this[previousIndex]

                                                            this[selectedIndex] =
                                                                componentToMoveToSelectedSlot
                                                            this[previousIndex] =
                                                                componentToMoveToOtherSlot
                                                        }

                                                    val adjustedComponents =
                                                        ensureRestSeparatedBySets(newSets)
                                                    val updatedExercise = exercise.copy(
                                                        sets = adjustedComponents,
                                                        requiredAccessoryEquipmentIds = exercise.requiredAccessoryEquipmentIds
                                                            ?: emptyList()
                                                    )

                                                    updateExerciseWithHistory(updatedExercise)
                                                    pendingSetBringIntoViewId = selectedComponent.id
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
                                                textAlign = TextAlign.Center
                                            )
                                        }
                                        Column(
                                            horizontalAlignment = Alignment.CenterHorizontally,
                                            modifier = Modifier
                                                .width(56.dp)
                                        ) {
                                            IconButton(
                                                enabled = selectedSets.size == 1 &&
                                                        exercise.sets.indexOfFirst { it.id == selectedSets.first().id } != exercise.sets.size - 1,
                                                onClick = {
                                                    val currentSets = exercise.sets
                                                    val selectedComponent = selectedSets.first()

                                                    val selectedIndex =
                                                        currentSets.indexOfFirst { it.id == selectedComponent.id }

                                                    if (selectedIndex < 0 || selectedIndex + 1 >= currentSets.size) {
                                                        return@IconButton
                                                    }

                                                    val nextIndex = selectedIndex + 1

                                                    val newSets =
                                                        currentSets.toMutableList().apply {
                                                            val componentToMoveToOtherSlot =
                                                                this[selectedIndex]
                                                            val componentToMoveToSelectedSlot =
                                                                this[nextIndex]

                                                            this[selectedIndex] =
                                                                componentToMoveToSelectedSlot
                                                            this[nextIndex] =
                                                                componentToMoveToOtherSlot
                                                        }

                                                    val adjustedComponents =
                                                        ensureRestSeparatedBySets(newSets)
                                                    val updatedExercise = exercise.copy(
                                                        sets = adjustedComponents,
                                                        requiredAccessoryEquipmentIds = exercise.requiredAccessoryEquipmentIds
                                                            ?: emptyList()
                                                    )

                                                    updateExerciseWithHistory(updatedExercise)
                                                    pendingSetBringIntoViewId = selectedComponent.id
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
                                                textAlign = TextAlign.Center
                                            )
                                        }
                                    }
                                    Column(
                                        horizontalAlignment = Alignment.CenterHorizontally,
                                        modifier = Modifier
                                            .width(56.dp)
                                    ) {
                                        IconButton(onClick = {
                                            val newSets = sets.filter { set ->
                                                selectedSets.none { it.id == set.id }
                                            }

                                            val adjustedComponents =
                                                ensureRestSeparatedBySets(newSets)
                                            val updatedExercise =
                                                exercise.copy(sets = adjustedComponents)

                                            updateExerciseWithHistory(updatedExercise)

                                            selectedSetIds = emptySet()
                                            isSelectionModeActive = false
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
                                            textAlign = TextAlign.Center
                                        )
                                    }
                                    Column(
                                        horizontalAlignment = Alignment.CenterHorizontally,
                                        modifier = Modifier
                                            .width(56.dp)
                                    ) {
                                        IconButton(
                                            enabled = selectedSets.isNotEmpty(),
                                            onClick = {
                                                val copiedSets = selectedSets.map {
                                                    when (it) {
                                                        is WeightSet -> it.copy(id = java.util.UUID.randomUUID())
                                                        is BodyWeightSet -> it.copy(id = java.util.UUID.randomUUID())
                                                        is EnduranceSet -> it.copy(id = java.util.UUID.randomUUID())
                                                        is TimedDurationSet -> it.copy(id = java.util.UUID.randomUUID())
                                                        is RestSet -> it.copy(id = java.util.UUID.randomUUID())
                                                        else -> throw IllegalArgumentException("Unknown type")
                                                    }
                                                }

                                                val adjustedComponents =
                                                    ensureRestSeparatedBySets(sets + copiedSets)
                                                val updatedExercise = exercise.copy(
                                                    sets = adjustedComponents,
                                                    requiredAccessoryEquipmentIds = exercise.requiredAccessoryEquipmentIds
                                                        ?: emptyList()
                                                )

                                                updateExerciseWithHistory(updatedExercise)

                                                selectedSetIds = emptySet()
                                            },
                                            colors = selectionIconColors
                                        ) {
                                            Icon(
                                                imageVector = Icons.Default.ContentCopy,
                                                contentDescription = "Copy"
                                            )
                                        }
                                        Text(
                                            "Copy",
                                            style = MaterialTheme.typography.labelSmall,
                                            textAlign = TextAlign.Center
                                        )
                                    }
                                }
                            }
                        )
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
                val isHistoryEnabled = !exercise.doNotStoreHistory
                val tabTitles = remember { listOf("Overview", "History") }

                var selectedTopTab by remember(exercise.id, initialSelectedTabIndex, isHistoryEnabled) {
                    mutableIntStateOf(
                        if (isHistoryEnabled) initialSelectedTabIndex.coerceIn(0, 1) else 0
                    )
                }

                LaunchedEffect(isHistoryEnabled, selectedTopTab) {
                    if (!isHistoryEnabled && selectedTopTab == 1) {
                        selectedTopTab = 0
                    }
                }

                SwipeableTabs(
                    tabTitles = tabTitles,
                    selectedTabIndex = selectedTopTab,
                    onTabSelected = { index ->
                        if (index == 1 && exercise.doNotStoreHistory) return@SwipeableTabs
                        selectedTopTab = index
                    },
                    tabEnabled = { index -> index == 0 || !exercise.doNotStoreHistory },
                    unselectedContentColor = if (isHistoryEnabled) {
                        MaterialTheme.colorScheme.onBackground
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                    modifier = Modifier.fillMaxSize(),
                    pagerModifier = Modifier.fillMaxSize()
                ) { pageIndex ->
                    when (pageIndex) {
                        0 -> ExerciseOverviewTab(
                            appViewModel = appViewModel,
                            workoutId = workout.id,
                            exercise = exercise,
                            sets = sets,
                            equipments = equipments,
                            selectedEquipmentId = selectedEquipmentId,
                            showRest = showRest,
                            onShowRestChange = { showRest = it },
                            selectedSets = selectedSets,
                            isSelectionModeActive = isSelectionModeActive,
                            onEnableSelection = { isSelectionModeActive = true },
                            onDisableSelection = { isSelectionModeActive = false },
                            onSelectedSetIdsChange = { selectedSetIds = it },
                            onSetsReordered = { adjustedComponents ->
                                val updatedExercise = exercise.copy(
                                    sets = adjustedComponents,
                                    requiredAccessoryEquipmentIds = exercise.requiredAccessoryEquipmentIds
                                        ?: emptyList()
                                )
                                updateExerciseWithHistory(updatedExercise)
                            },
                            pendingSetBringIntoViewId = pendingSetBringIntoViewId,
                            onPendingSetBringIntoViewConsumed = {
                                pendingSetBringIntoViewId = null
                            }
                        )

                        1 -> ExerciseHistoryTab(
                            appViewModel = appViewModel,
                            workout = workout,
                            workoutHistoryDao = workoutHistoryDao,
                            setHistoryDao = setHistoryDao,
                            exercise = exercise,
                            initialHistoryMode = initialHistoryMode,
                            onGoBack = onGoBack,
                            onNavigateToOverview = { selectedTopTab = 0 }
                        )
                    }
                }

            }
        }
        LoadingOverlay(isVisible = rememberDebouncedSavingVisible(isSaving), text = "Saving...")
    }
}
