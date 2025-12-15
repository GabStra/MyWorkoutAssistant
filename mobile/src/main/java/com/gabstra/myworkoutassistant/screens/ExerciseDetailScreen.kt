package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.interaction.Interaction
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.FileDownload
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.TabRowDefaults
import androidx.compose.material3.TabRowDefaults.tabIndicatorOffset
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.GenericButtonWithMenu
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.MenuItem
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.ensureRestSeparatedBySets
import com.gabstra.myworkoutassistant.exportExerciseHistoryToMarkdown
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun ComponentRenderer(set: Set, appViewModel: AppViewModel,exercise: Exercise) {
    // Observe equipmentsFlow to fix race condition - recompose when equipments are loaded
    val equipments by appViewModel.equipmentsFlow.collectAsState()
    
    when (set) {
        is WeightSet -> {
            val equipment = exercise.equipmentId?.let { appViewModel.getEquipmentById(it) }

            StyledCard {
                Row(
                    modifier = Modifier.padding(15.dp),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {

                        Text(
                            text = if (equipment != null) {
                                "Weight (KG): ${equipment.formatWeight(set.weight)}"
                            } else {
                                "Weight (KG): ${set.weight}"
                            },
                            color = MaterialTheme.colorScheme.onBackground,
                            style = MaterialTheme.typography.bodyMedium,)
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

        is BodyWeightSet -> {
            val equipment = exercise.equipmentId?.let { appViewModel.getEquipmentById(it) }

            StyledCard {
                Row(
                    modifier = Modifier.padding(15.dp),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        if(set.additionalWeight != 0.0 && equipment != null){
                            Text(
                                text = "Weight (KG): ${equipment.formatWeight(set.additionalWeight)}",
                                color = MaterialTheme.colorScheme.onBackground,
                                style = MaterialTheme.typography.bodyMedium,
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

        is EnduranceSet -> {
            StyledCard {
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
            StyledCard {
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
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                StyledCard(modifier = Modifier.wrapContentSize(), ) {
                    Row(
                        modifier = Modifier.padding(15.dp),
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = "Rest ${formatTime(set.timeInSeconds)}",
                            textAlign = TextAlign.Center,
                             color = MaterialTheme.colorScheme.onBackground,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }
            }
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
    onGoBack: () -> Unit
) {
    var sets by remember { mutableStateOf(ensureRestSeparatedBySets(exercise.sets)) }
    var selectedSets by remember { mutableStateOf(listOf<Set>()) }

    var isSelectionModeActive by remember { mutableStateOf(false) }
    var showRest by remember { mutableStateOf(false) }

    val equipments by appViewModel.equipmentsFlow.collectAsState()
    val selectedEquipmentId = exercise?.equipmentId
    val workouts by appViewModel.workoutsFlow.collectAsState()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    LaunchedEffect(showRest) {
        selectedSets = emptyList()
    }

    LaunchedEffect(exercise.sets) {
        // Sync sets state when exercise parameter changes
        sets = ensureRestSeparatedBySets(exercise.sets)
        
        // Sync selectedSets with new set references when exercise updates
        if (selectedSets.isNotEmpty()) {
            val selectedIds = selectedSets.map { it.id }.toSet()
            selectedSets = exercise.sets.filter { it.id in selectedIds }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background, titleContentColor = MaterialTheme.colorScheme.onBackground),
                title = {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .basicMarquee(iterations = Int.MAX_VALUE),
                        textAlign = TextAlign.Center,
                        text = exercise.name
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
                    IconButton(
                        enabled = !exercise.doNotStoreHistory,
                        onClick = {
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
                    ) {
                        Icon(
                            imageVector = Icons.Default.FileDownload,
                            contentDescription = "Export History",
                            tint = if (exercise.doNotStoreHistory) MaterialTheme.colorScheme.onBackground else MaterialTheme.colorScheme.onBackground
                        )
                    }
                    IconButton(onClick = {
                        appViewModel.setScreenData(
                            ScreenData.EditExercise(
                                workout.id,
                                exercise.id
                            )
                        );
                    }) {
                        Icon(
                            imageVector = Icons.Default.Settings,
                            contentDescription = "Settings"
                        )
                    }
                }
            )
        },
        bottomBar = {
            if (selectedSets.isNotEmpty()) {
                StyledCard{
                    BottomAppBar(
                        contentPadding = PaddingValues(0.dp),
                        containerColor = Color.Transparent,
                        actions = {
                            Row(
                                modifier = Modifier
                                    .fillMaxSize(),
                                horizontalArrangement = Arrangement.SpaceEvenly,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                IconButton(
                                    enabled = selectedSets.size == 1 &&
                                            exercise.sets.indexOfFirst { it.id == selectedSets.first().id } != 0 &&
                                            selectedSets.first() !is RestSet,
                                    onClick = {
                                        val currentSets = exercise.sets
                                        val selectedComponent = selectedSets.first()

                                        val selectedIndex =
                                            currentSets.indexOfFirst { it.id == selectedComponent.id }

                                        val previousComponent = currentSets.subList(0, selectedIndex)
                                            .lastOrNull { it !is RestSet }

                                        if (previousComponent == null) {
                                            return@IconButton
                                        }

                                        val previous = currentSets.indexOfFirst { it.id == previousComponent.id }

                                        val newSets = currentSets.toMutableList().apply {
                                            val componentToMoveToOtherSlot = this[selectedIndex]
                                            val componentToMoveToSelectedSlot = this[previous]

                                            this[selectedIndex] = componentToMoveToSelectedSlot
                                            this[previous] = componentToMoveToOtherSlot
                                        }

                                        val adjustedComponents = ensureRestSeparatedBySets(newSets)
                                        val updatedExercise = exercise.copy(sets = adjustedComponents)

                                        appViewModel.updateWorkoutComponentOld(
                                            workout,
                                            exercise,
                                            updatedExercise
                                        )

                                        sets = adjustedComponents
                                    }) {
                                    Icon(
                                        imageVector = Icons.Filled.ArrowUpward,
                                        contentDescription = "Go Higher",
                                        tint = MaterialTheme.colorScheme.onBackground
                                    )
                                }

                                IconButton(
                                    enabled = selectedSets.size == 1 &&
                                            exercise.sets.indexOfFirst { it.id == selectedSets.first().id } != exercise.sets.size - 1 &&
                                            selectedSets.first() !is RestSet,
                                    onClick = {
                                        val currentSets = exercise.sets
                                        val selectedComponent = selectedSets.first()

                                        val selectedIndex =
                                            currentSets.indexOfFirst { it.id == selectedComponent.id }

                                        val nextComponent = if (selectedIndex + 1 < currentSets.size) {
                                            currentSets.subList(selectedIndex + 1, currentSets.size)
                                                .firstOrNull { it !is RestSet }
                                        } else {
                                            null
                                        }

                                        if (nextComponent == null) {
                                            return@IconButton
                                        }

                                        val nextIndex = currentSets.indexOfFirst { it.id == nextComponent.id }

                                        val newSets = currentSets.toMutableList().apply {
                                            val componentToMoveToOtherSlot = this[selectedIndex]
                                            val componentToMoveToSelectedSlot = this[nextIndex]

                                            this[selectedIndex] = componentToMoveToSelectedSlot
                                            this[nextIndex] = componentToMoveToOtherSlot
                                        }

                                        val adjustedComponents = ensureRestSeparatedBySets(newSets)
                                        val updatedExercise = exercise.copy(sets = adjustedComponents)

                                        sets = adjustedComponents

                                        appViewModel.updateWorkoutComponentOld(
                                            workout,
                                            exercise,
                                            updatedExercise
                                        )
                                    }) {
                                    Icon(
                                        imageVector = Icons.Filled.ArrowDownward,
                                        contentDescription = "Go Lower"
                                        ,tint = MaterialTheme.colorScheme.onBackground
                                    )
                                }

                                IconButton(onClick = {
                                    val newSets = sets.filter { set ->
                                        selectedSets.none { it.id == set.id }
                                    }

                                    val adjustedComponents = ensureRestSeparatedBySets(newSets)
                                    val updatedExercise = exercise.copy(sets = adjustedComponents)

                                    sets = adjustedComponents

                                    appViewModel.updateWorkoutComponentOld(
                                        workout,
                                        exercise,
                                        updatedExercise
                                    )

                                    selectedSets = emptyList()
                                    isSelectionModeActive = false
                                }) {
                                    Icon(
                                        imageVector = Icons.Default.Delete,
                                        contentDescription = "Delete",
                                        tint = MaterialTheme.colorScheme.onBackground
                                    )
                                }
                                IconButton(
                                    enabled = selectedSets.isNotEmpty(),
                                    onClick = {
                                        selectedSets.forEach {
                                            val newSet = when (it) {
                                                is WeightSet -> it.copy(id = java.util.UUID.randomUUID())
                                                is BodyWeightSet -> it.copy(id = java.util.UUID.randomUUID())
                                                is EnduranceSet -> it.copy(id = java.util.UUID.randomUUID())
                                                is TimedDurationSet -> it.copy(id = java.util.UUID.randomUUID())
                                                is RestSet -> it.copy(id = java.util.UUID.randomUUID())
                                                else -> throw IllegalArgumentException("Unknown type")
                                            }
                                            appViewModel.addSetToExercise(workout, exercise, newSet)
                                            sets = sets + newSet
                                        }

                                        val adjustedComponents = ensureRestSeparatedBySets(sets)
                                        val updatedExercise = exercise.copy(sets = adjustedComponents)

                                        sets = adjustedComponents

                                        appViewModel.updateWorkoutComponentOld(
                                            workout,
                                            exercise,
                                            updatedExercise
                                        )

                                        selectedSets = emptyList()
                                    }) {
                                    val isEnabled = selectedSets.isNotEmpty()
                                    val color = if (isEnabled) MaterialTheme.colorScheme.onBackground else MaterialTheme.colorScheme.onBackground

                                    Icon(imageVector = Icons.Default.ContentCopy, contentDescription = "Copy",tint = color)
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
                TabRow(
                    modifier = Modifier.fillMaxWidth(),
                    containerColor = MaterialTheme.colorScheme.background,
                    contentColor = MaterialTheme.colorScheme.onBackground,
                    selectedTabIndex = 0,
                    indicator = { tabPositions ->
                        TabRowDefaults.Indicator(
                            Modifier.tabIndicatorOffset(tabPositions[0]),
                            color = MaterialTheme.colorScheme.primary, // Set the indicator color
                            height = 2.dp // Set the indicator thickness
                        )
                    }
                ) {
                    Tab(
                        modifier = Modifier.background(MaterialTheme.colorScheme.background),
                        selected = true,
                        onClick = { },
                        text = { Text(text = "Overview") },
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
                        enabled = !exercise.doNotStoreHistory,
                        selected = false,
                        onClick = {
                            appViewModel.setScreenData(
                                ScreenData.ExerciseHistory(workout.id, exercise.id),
                                true
                            )
                        },
                        text = { Text(text = "History") },
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
                        .verticalColumnScrollbar(scrollState)
                        .verticalScroll(scrollState)
                        .padding(horizontal = 15.dp),
                ) {
                    if (sets.isEmpty()) {
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(5.dp),
                            horizontalArrangement = Arrangement.Center,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Button(
                                colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
                                onClick = {
                                    appViewModel.setScreenData(
                                        ScreenData.NewSet(workout.id, exercise.id)
                                    );
                                },
                            ) {
                                Text("Add Set")
                            }
                        }
                    }else{
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 15.dp)
                        ) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(5.dp),
                                modifier = Modifier.then(
                                    if (selectedEquipmentId == null) Modifier.alpha(
                                        0f
                                    ) else Modifier
                                )
                            ) {
                                Text(text = "Equipment:", style = MaterialTheme.typography.bodyMedium)
                                val selectedEquipment = if(selectedEquipmentId == null) null else equipments.find { it.id == selectedEquipmentId }
                                Text(
                                    text = selectedEquipment?.name ?: "None",
                                    style = MaterialTheme.typography.bodyMedium
                                )
                            }

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
                                Text(text = "Show Rests", style = MaterialTheme.typography.bodyMedium)
                            }
                        }

                        GenericSelectableList(
                            it = null,
                            items = if (!showRest) sets.filter { it !is RestSet } else sets,
                            selectedItems = selectedSets,
                            isSelectionModeActive,
                            onItemClick = {
                                if (it is RestSet) {
                                    appViewModel.setScreenData(
                                        ScreenData.EditRestSet(
                                            workout.id,
                                            it,
                                            exercise.id
                                        )
                                    )
                                } else {
                                    appViewModel.setScreenData(
                                        ScreenData.EditSet(
                                            workout.id,
                                            it,
                                            exercise.id
                                        )
                                    )
                                }
                            },
                            onEnableSelection = { isSelectionModeActive = true },
                            onDisableSelection = { isSelectionModeActive = false },
                            onSelectionChange = { newSelection -> selectedSets = newSelection },
                            onOrderChange = { newComponents ->
                                if (!showRest) return@GenericSelectableList
                                val adjustedComponents = ensureRestSeparatedBySets(newComponents)
                                val updatedExercise = exercise.copy(sets = adjustedComponents)
                                appViewModel.updateWorkoutComponentOld(workout, exercise, updatedExercise)
                                sets = adjustedComponents
                            },
                            isDragDisabled = true,
                            itemContent = { it ->
                                ComponentRenderer(it, appViewModel, exercise)
                            }
                        )
                        Row(
                            modifier = Modifier
                                .fillMaxSize(),
                            horizontalArrangement = Arrangement.Center, // Space items evenly, including space at the edges
                            verticalAlignment = Alignment.CenterVertically // Center items vertically within the Row
                        ) {
                            GenericButtonWithMenu(
                                menuItems = listOf(
                                    MenuItem("Add Set") {
                                        appViewModel.setScreenData(
                                            ScreenData.NewSet(workout.id, exercise.id)
                                        );
                                    },
                                    MenuItem("Add Rests between sets") {
                                        appViewModel.setScreenData(
                                            ScreenData.NewRestSet(workout.id, exercise.id)
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
                }
            }

    }
}

