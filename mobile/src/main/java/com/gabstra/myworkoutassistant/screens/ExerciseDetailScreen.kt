package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.composables.BreadcrumbScaffold

import android.annotation.SuppressLint
import android.net.Uri
import android.util.Log
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.QuestionAnswer
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.CheckBox
import androidx.compose.material.icons.filled.CheckBoxOutlineBlank
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.BottomAppBar
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
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.MobileLlmFeatureFlags
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.AppDropdownMenu
import com.gabstra.myworkoutassistant.composables.AppDropdownMenuItem
import com.gabstra.myworkoutassistant.composables.ConfirmationDialog
import com.gabstra.myworkoutassistant.composables.LoadingOverlay
import com.gabstra.myworkoutassistant.composables.StableHeaderIconButton
import com.gabstra.myworkoutassistant.composables.SwipeableTabs
import com.gabstra.myworkoutassistant.composables.rememberDebouncedSavingVisible
import com.gabstra.myworkoutassistant.shared.FilterRange
import com.gabstra.myworkoutassistant.ensureRestSeparatedBySets
import com.gabstra.myworkoutassistant.exportExerciseHistoryToMarkdown
import com.gabstra.myworkoutassistant.insights.ConfigurableWorkoutInsightsEngine
import com.gabstra.myworkoutassistant.insights.InsightTokenCounter
import com.gabstra.myworkoutassistant.insights.LiteRtLmModelStore
import com.gabstra.myworkoutassistant.insights.WorkoutInsightsRequest
import com.gabstra.myworkoutassistant.insights.WorkoutInsightsSettingsStore
import com.gabstra.myworkoutassistant.insights.WorkoutInsightsDialog
import com.gabstra.myworkoutassistant.insights.WorkoutInsightsPromptResult
import com.gabstra.myworkoutassistant.insights.WorkoutInsightsUiState
import com.gabstra.myworkoutassistant.insights.buildExerciseInsightsPrompt
import com.gabstra.myworkoutassistant.insights.settledMarkdownPrefix
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.RestHistoryDao
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.RunningSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightedEffortSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.UUID

private const val INSIGHTS_LOG_TAG = "WorkoutInsights"

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
                contentDescription = stringResource(R.string.history_more_cd)
            )
        }

        AppDropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false }
        ) {
            AppDropdownMenuItem(
                text = { Text(text = stringResource(R.string.loc_ex_edit_exercise_menu), fontWeight = FontWeight.Normal) },
                onClick = {
                    onEditExercise()
                    expanded = false
                }
            )
            HorizontalDivider(
                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f)
            )
            AppDropdownMenuItem(
                text = { Text(text = stringResource(R.string.loc_ex_export_md), fontWeight = FontWeight.Normal) },
                enabled = isExportEnabled,
                onClick = {
                    onExportExerciseHistory()
                    expanded = false
                }
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
    restHistoryDao: RestHistoryDao,
    exercise: Exercise,
    initialSelectedTabIndex: Int = 0,
    initialWorkoutHistoryId: UUID? = null,
    onGoBack: () -> Unit
) {
    val sets = remember(exercise.sets) { ensureRestSeparatedBySets(exercise.sets) }
    var selectedSetIds by remember { mutableStateOf(setOf<UUID>()) }
    val selectedSets = remember(sets, selectedSetIds) {
        sets.filter { it.id in selectedSetIds }
    }

    var isSelectionModeActive by remember { mutableStateOf(false) }
    var showDeleteSetsDialog by remember { mutableStateOf(false) }
    var showRest by remember { mutableStateOf(true) }
    var pendingSetBringIntoViewId by remember { mutableStateOf<UUID?>(null) }
    val overviewTabTitle = stringResource(R.string.loc_scr_tab_overview)
    val chartsTabTitle = stringResource(R.string.loc_scr_tab_charts)
    val historiesTabTitle = stringResource(R.string.loc_scr_tab_histories)
    val tabTitles = remember(overviewTabTitle, chartsTabTitle, historiesTabTitle) {
        listOf(overviewTabTitle, chartsTabTitle, historiesTabTitle)
    }
    val historyTabStartIndex = 1
    val historyTabRange = historyTabStartIndex..(historyTabStartIndex + 1)
    var selectedTopTab by remember(exercise.id, initialSelectedTabIndex) {
        mutableIntStateOf(initialSelectedTabIndex.coerceIn(0, tabTitles.lastIndex))
    }
    var displayedWorkoutHistoryId by remember(workout.id, exercise.id) {
        mutableStateOf(initialWorkoutHistoryId)
    }
    var historyActionsLoading by remember(workout.id, exercise.id, initialSelectedTabIndex) {
        mutableStateOf(initialSelectedTabIndex in 1..2)
    }
    var historyFilterRange by remember(workout.id, exercise.id) {
        mutableStateOf(FilterRange.ALL)
    }
    var isHistoryFiltersExpanded by rememberSaveable(workout.id, exercise.id) {
        mutableStateOf(true)
    }

    val equipments by appViewModel.equipmentsFlow.collectAsState()
    val selectedEquipmentId = exercise.equipmentId
    val workouts by appViewModel.workoutsFlow.collectAsState()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var isSaving by remember { mutableStateOf(false) }
    var showInsightsDialog by remember { mutableStateOf(false) }
    var insightsState by remember { mutableStateOf<WorkoutInsightsUiState>(WorkoutInsightsUiState.Idle) }
    var insightsConfigurationVersion by remember { mutableIntStateOf(0) }
    val insightsRepository = remember(context) { ConfigurableWorkoutInsightsEngine(context.applicationContext) }
    val insightsConfigurationState = remember(showInsightsDialog, insightsState, insightsConfigurationVersion) {
        WorkoutInsightsSettingsStore.getConfigurationState(context)
    }
    val modelPickerLauncher =
        rememberLauncherForActivityResult(contract = ActivityResultContracts.OpenDocument()) { uri: Uri? ->
            uri ?: return@rememberLauncherForActivityResult
            scope.launch {
                insightsState = WorkoutInsightsUiState.ImportingModel
                runCatching {
                    withContext(Dispatchers.IO) {
                        LiteRtLmModelStore.importModel(context, uri)
                    }
                }.onSuccess {
                    insightsConfigurationVersion++
                    insightsState = WorkoutInsightsUiState.Idle
                }.onFailure { error ->
                    insightsState = WorkoutInsightsUiState.Error(
                        error.message ?: context.getString(R.string.loc_ex_unable_import_model)
                    )
                }
            }
        }

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
                    restHistoryDao = db.restHistoryDao(),
                    exerciseSessionProgressionDao = exerciseSessionProgressionDao,
                    workouts = workouts,
                    workoutStore = appViewModel.workoutStore
                )
            }
        }
    }

    fun generateExerciseInsights() {
        if (!MobileLlmFeatureFlags.isEnabled(context)) return
        showInsightsDialog = true
        scope.launch {
            insightsState = WorkoutInsightsUiState.PreparingModel
            when (
                val promptResult = withContext(Dispatchers.IO) {
                    InsightTokenCounter.loadNow(context)
                    val db = AppDatabase.getDatabase(context)
                    buildExerciseInsightsPrompt(
                        exercise = exercise,
                        workoutHistoryDao = workoutHistoryDao,
                        setHistoryDao = setHistoryDao,
                        restHistoryDao = db.restHistoryDao(),
                        exerciseSessionProgressionDao = db.exerciseSessionProgressionDao(),
                        workouts = workouts,
                        workoutStore = appViewModel.workoutStore
                    )
                }
            ) {
                is WorkoutInsightsPromptResult.Failure -> {
                    insightsState = WorkoutInsightsUiState.Error(promptResult.message)
                }
                is WorkoutInsightsPromptResult.Success -> {
                    Log.d(
                        INSIGHTS_LOG_TAG,
                        "exercise_prompt_start\n${promptResult.prompt}\nexercise_prompt_end"
                    )
                    // Holds the full final chunk text (post-processed); Generating.partialText
                    // carries only settled markdown blocks for the streaming reveal.
                    var finalText = ""
                    var finalDisplayText = ""
                    runCatching {
                        insightsRepository.generateInsights(
                            WorkoutInsightsRequest(
                                title = promptResult.title,
                                prompt = promptResult.prompt,
                                systemPrompt = promptResult.systemPrompt,
                                toolContext = promptResult.toolContext,
                                useTransportToolCalling = true,
                            )
                        ).collectLatest { chunk ->
                            val displayText = chunk.displayText ?: chunk.text
                            finalText = chunk.text
                            finalDisplayText = displayText
                            insightsState = WorkoutInsightsUiState.Generating(
                                partialText = settledMarkdownPrefix(displayText),
                                phase = chunk.phase,
                                statusText = chunk.statusText
                            )
                        }
                    }.onSuccess {
                        Log.d(
                            INSIGHTS_LOG_TAG,
                            "exercise_raw_response_start\n${finalText.ifBlank { context.getString(R.string.loc_scr_no_insights_generated) }}\nexercise_raw_response_end"
                        )
                        insightsState = WorkoutInsightsUiState.Success(
                            title = promptResult.title,
                            text = finalDisplayText.ifBlank {
                                context.getString(R.string.loc_scr_no_insights_generated)
                            }
                        )
                    }.onFailure { error ->
                        insightsState = WorkoutInsightsUiState.Error(
                            error.message ?: context.getString(R.string.loc_scr_unable_generate_insights)
                        )
                    }
                }
            }
        }
    }

    LaunchedEffect(showRest) {
        selectedSetIds = emptySet()
    }

    LaunchedEffect(initialWorkoutHistoryId) {
        if (initialWorkoutHistoryId != displayedWorkoutHistoryId) {
            displayedWorkoutHistoryId = initialWorkoutHistoryId
        }
    }

    LaunchedEffect(selectedTopTab) {
        if (selectedTopTab !in historyTabRange) {
            historyActionsLoading = false
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        val showHistoryActions = MobileLlmFeatureFlags.isEnabled(context) && selectedTopTab in historyTabRange
        val enableHistoryActions = showHistoryActions && !historyActionsLoading
        BreadcrumbScaffold(
            showTopBarDivider = false,
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
                            modifier = Modifier.fillMaxWidth(),
                            textAlign = TextAlign.Center,
                            text = exercise.name,
                            maxLines = 2,
                            overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                            style = MaterialTheme.typography.titleLarge,
                            color = MaterialTheme.colorScheme.onBackground
                        )
                    },
                    navigationIcon = {
                        IconButton(onClick = onGoBack) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                contentDescription = stringResource(R.string.common_back)
                            )
                        }
                    },

                    actions = {
                        StableHeaderIconButton(
                            visible = showHistoryActions,
                            enabled = enableHistoryActions,
                            onClick = {
                                appViewModel.setScreenData(
                                    ScreenData.HistoryChatExercise(
                                        workoutId = workout.id,
                                        exerciseId = exercise.id,
                                    )
                                )
                            }
                        ) {
                            Icon(
                                imageVector = Icons.Default.QuestionAnswer,
                                contentDescription = stringResource(R.string.loc_ex_chat_with_history_cd)
                            )
                        }
                        StableHeaderIconButton(
                            visible = showHistoryActions,
                            enabled = enableHistoryActions,
                            onClick = {
                                showInsightsDialog = true
                                insightsState = WorkoutInsightsUiState.Idle
                            }
                        ) {
                            Icon(
                                imageVector = Icons.Default.AutoAwesome,
                                contentDescription = stringResource(R.string.loc_scr_insights_cd)
                            )
                        }
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
                            isExportEnabled = true
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
                                                contentDescription = stringResource(R.string.common_close),
                                                tint = Red
                                            )
                                        }
                                        Text(
                                            stringResource(R.string.common_close),
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
                                                contentDescription = stringResource(R.string.loc_select_all),
                                                tint = MaterialTheme.colorScheme.onBackground
                                            )
                                        }
                                        Text(
                                            stringResource(R.string.loc_select_all),
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
                                                contentDescription = stringResource(R.string.loc_deselect_all),
                                                tint = MaterialTheme.colorScheme.onBackground
                                            )
                                        }
                                        Text(
                                            stringResource(R.string.loc_deselect_all),
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
                                                    contentDescription = stringResource(R.string.loc_ex_move_up),
                                                )
                                            }
                                            Text(
                                                stringResource(R.string.loc_ex_move_up),
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
                                                    contentDescription = stringResource(R.string.loc_ex_move_down)
                                                )
                                            }
                                            Text(
                                                stringResource(R.string.loc_ex_move_down),
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
                                            showDeleteSetsDialog = true
                                        }) {
                                            Icon(
                                                imageVector = Icons.Default.Delete,
                                                contentDescription = stringResource(R.string.common_delete),
                                                tint = MaterialTheme.colorScheme.onBackground
                                            )
                                        }
                                        Text(
                                            stringResource(R.string.common_delete),
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
                                                        is RunningSet -> it.copy(id = java.util.UUID.randomUUID())
                                                        is TimedDurationSet -> it.copy(id = java.util.UUID.randomUUID())
                                                        is WeightedEffortSet -> it.copy(id = java.util.UUID.randomUUID())
                                                        is RestSet -> it.copy(id = java.util.UUID.randomUUID())
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
                                                contentDescription = stringResource(R.string.loc_copy)
                                            )
                                        }
                                        Text(
                                            stringResource(R.string.loc_copy),
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
                SwipeableTabs(
                    tabTitles = tabTitles,
                    selectedTabIndex = selectedTopTab,
                    onTabSelected = { index ->
                        selectedTopTab = index
                        historyActionsLoading = index in historyTabRange
                        val targetScreenData = ScreenData.ExerciseDetail(
                            workoutId = workout.id,
                            selectedExerciseId = exercise.id,
                            selectedTabIndex = index,
                            workoutHistoryId = if (index in historyTabRange) displayedWorkoutHistoryId else null,
                        )
                        appViewModel.updateScreenDataIfChanged(targetScreenData)
                    },
                    tabEnabled = { true },
                    unselectedContentColor = MaterialTheme.colorScheme.onBackground,
                    beyondViewportPageCount = 1,
                    modifier = Modifier.fillMaxSize(),
                    pagerModifier = Modifier.fillMaxSize(),
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

                        1, 2 -> ExerciseHistoryScreen(
                            appViewModel = appViewModel,
                            workout = workout,
                            workoutHistoryDao = workoutHistoryDao,
                            setHistoryDao = setHistoryDao,
                            restHistoryDao = restHistoryDao,
                            exercise = exercise,
                            workoutHistoryId = displayedWorkoutHistoryId,
                            selectedHistoryMode = pageIndex - historyTabStartIndex,
                            historyFilterRange = historyFilterRange,
                            onHistoryFilterRangeChange = { historyFilterRange = it },
                            isHistoryFiltersExpanded = isHistoryFiltersExpanded,
                            onHistoryFiltersExpandedChange = { isHistoryFiltersExpanded = it },
                            onGoBack = onGoBack,
                            onSelectedWorkoutHistoryIdChanged = { id ->
                                if (pageIndex == selectedTopTab) {
                                    if (displayedWorkoutHistoryId != id) {
                                        displayedWorkoutHistoryId = id
                                    }
                                    historyActionsLoading = false
                                    val targetScreenData = ScreenData.ExerciseDetail(
                                        workoutId = workout.id,
                                        selectedExerciseId = exercise.id,
                                        selectedTabIndex = selectedTopTab,
                                        workoutHistoryId = id,
                                    )
                                    appViewModel.updateScreenDataIfChanged(targetScreenData)
                                }
                            },
                        )
                    }
                }

                LaunchedEffect(selectedTopTab, workout.id, exercise.id, displayedWorkoutHistoryId) {
                    val targetScreenData = ScreenData.ExerciseDetail(
                        workoutId = workout.id,
                        selectedExerciseId = exercise.id,
                        selectedTabIndex = selectedTopTab,
                        workoutHistoryId = if (selectedTopTab in historyTabRange) displayedWorkoutHistoryId else null,
                    )
                    appViewModel.updateScreenDataIfChanged(targetScreenData)
                }

            }
        }
        ConfirmationDialog(
            show = showDeleteSetsDialog,
            title = if (selectedSets.size == 1) {
                stringResource(R.string.loc_ex_delete_selected_set_title)
            } else {
                stringResource(R.string.loc_ex_delete_selected_sets_title)
            },
            message = if (selectedSets.size == 1) {
                stringResource(R.string.loc_ex_delete_selected_set_message)
            } else {
                stringResource(R.string.loc_ex_delete_selected_sets_message, selectedSets.size)
            },
            confirmText = stringResource(R.string.common_delete),
            isDestructive = true,
            onConfirm = {
                val newSets = sets.filter { set ->
                    selectedSets.none { it.id == set.id }
                }

                val adjustedComponents = ensureRestSeparatedBySets(newSets)
                val updatedExercise = exercise.copy(sets = adjustedComponents)

                updateExerciseWithHistory(updatedExercise)

                selectedSetIds = emptySet()
                isSelectionModeActive = false
                showDeleteSetsDialog = false
            },
            onDismiss = {
                showDeleteSetsDialog = false
            }
        )
        LoadingOverlay(
            isVisible = rememberDebouncedSavingVisible(isSaving),
            text = stringResource(R.string.common_saving),
        )
        if (MobileLlmFeatureFlags.isEnabled(context)) {
            WorkoutInsightsDialog(
                show = showInsightsDialog,
                title = stringResource(R.string.loc_ex_insights_title),
                state = insightsState,
                configurationState = insightsConfigurationState,
                onDismiss = { showInsightsDialog = false },
                onConfigure = when (insightsConfigurationState.mode) {
                    com.gabstra.myworkoutassistant.insights.WorkoutInsightsMode.LOCAL -> {
                        { modelPickerLauncher.launch(LiteRtLmModelStore.pickerMimeTypes) }
                    }
                    com.gabstra.myworkoutassistant.insights.WorkoutInsightsMode.REMOTE -> {
                        {
                            showInsightsDialog = false
                            appViewModel.setScreenData(ScreenData.Settings())
                        }
                    }
                },
                onGenerate = { generateExerciseInsights() },
            )
        }
    }
}
