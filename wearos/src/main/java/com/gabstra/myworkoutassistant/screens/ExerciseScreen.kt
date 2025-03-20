package com.gabstra.myworkoutassistant.screens

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowForward
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Devices
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.ScalingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberScalingLazyListState
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text

import com.gabstra.myworkoutassistant.composable.BodyWeightSetScreen
import com.gabstra.myworkoutassistant.composable.ButtonWithText
import com.gabstra.myworkoutassistant.composable.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composable.CustomHorizontalPager
import com.gabstra.myworkoutassistant.composable.EnduranceSetScreen
import com.gabstra.myworkoutassistant.composable.ExerciseIndicator
import com.gabstra.myworkoutassistant.composable.ExerciseSetsViewer
import com.gabstra.myworkoutassistant.composable.TimedDurationSetScreen
import com.gabstra.myworkoutassistant.composable.WeightSetScreen
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.VibrateGentle
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.data.circleMask
import com.gabstra.myworkoutassistant.data.verticalColumnScrollbar
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Equipment
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import java.time.LocalDateTime
import java.util.UUID


@Composable
fun ExerciseDetail(
    updatedState: WorkoutState.Set, // Assuming SetState is the type holding set
    viewModel: AppViewModel,
    onEditModeDisabled: () -> Unit,
    onEditModeEnabled: () -> Unit,
    onTimerDisabled: () -> Unit,
    onTimerEnabled: () -> Unit,
    extraInfo: (@Composable (WorkoutState.Set) -> Unit)? = null,
    exerciseTitleComposable: @Composable () -> Unit,
) {
    val context = LocalContext.current

    when (updatedState.set) {
        is WeightSet -> {
            LaunchedEffect(updatedState) {
                if (updatedState.startTime == null) {
                    updatedState.startTime = LocalDateTime.now()
                }
            }

            WeightSetScreen(
                viewModel = viewModel,
                modifier = Modifier.fillMaxSize(),
                state = updatedState,
                forceStopEditMode = false,
                onEditModeDisabled = onEditModeDisabled,
                onEditModeEnabled = onEditModeEnabled,
                extraInfo = extraInfo,
                exerciseTitleComposable = exerciseTitleComposable
            )
        }

        is BodyWeightSet -> {
            LaunchedEffect(updatedState) {
                if (updatedState.startTime == null) {
                    updatedState.startTime = LocalDateTime.now()
                }
            }

            BodyWeightSetScreen(
                viewModel = viewModel,
                modifier = Modifier.fillMaxSize(),
                state = updatedState,
                forceStopEditMode = false,
                onEditModeDisabled = onEditModeDisabled,
                onEditModeEnabled = onEditModeEnabled,
                extraInfo = extraInfo,
                exerciseTitleComposable = exerciseTitleComposable
            )
        }

        is TimedDurationSet -> {
            TimedDurationSetScreen(
                viewModel = viewModel,
                modifier = Modifier.fillMaxSize(),
                state = updatedState,
                onTimerEnd = {
                    viewModel.storeSetData()
                    viewModel.pushAndStoreWorkoutData(false, context) {
                        viewModel.upsertWorkoutRecord(updatedState.set.id)
                        viewModel.goToNextState()
                        viewModel.lightScreenUp()
                    }
                },
                onTimerDisabled = onTimerDisabled,
                onTimerEnabled = onTimerEnabled,
                extraInfo = extraInfo,
                exerciseTitleComposable = exerciseTitleComposable
            )
        }

        is EnduranceSet -> EnduranceSetScreen(
            viewModel = viewModel,
            modifier = Modifier.fillMaxSize(),
            state = updatedState,
            onTimerEnd = {
                viewModel.storeSetData()
                viewModel.pushAndStoreWorkoutData(false, context) {
                    viewModel.upsertWorkoutRecord(updatedState.set.id)
                    viewModel.goToNextState()
                    viewModel.lightScreenUp()
                }
            },
            onTimerDisabled = onTimerDisabled,
            onTimerEnabled = onTimerEnabled,
            extraInfo = extraInfo,
            exerciseTitleComposable = exerciseTitleComposable
        )

        is RestSet -> throw IllegalStateException("Rest set should not be here")
    }
}

@Composable
fun PageExercises(
    currentStateSet: WorkoutState.Set,
    viewModel: AppViewModel,
    currentExercise: Exercise,
) {
    val exerciseIds = viewModel.setsByExerciseId.keys.toList()
    val exerciseOrSupersetIds = remember { viewModel.setsByExerciseId.keys.toList().map { if(viewModel.supersetIdByExerciseId.containsKey(it)) viewModel.supersetIdByExerciseId[it] else it }.distinct() }

    var marqueeEnabled by remember { mutableStateOf(false) }

    val currentExerciseIndex = exerciseIds.indexOf(currentExercise.id)

    val currentExerciseOrSupersetId = if(viewModel.supersetIdByExerciseId.containsKey(currentExercise.id)) viewModel.supersetIdByExerciseId[currentExercise.id] else currentExercise.id
    val currentExerciseOrSupersetIndex = exerciseOrSupersetIds.indexOf(currentExerciseOrSupersetId)

    var currentIndex by remember { mutableIntStateOf(currentExerciseIndex) }
    var selectedExercise by remember { mutableStateOf(currentExercise) }

    val typography = MaterialTheme.typography
    val captionStyle = remember { typography.body1.copy(fontSize = typography.body1.fontSize * 0.625f) }

    var isNavigationLocked by remember { mutableStateOf(false) }

    val isSuperset = remember(currentExerciseOrSupersetId) { viewModel.exercisesBySupersetId.containsKey(currentExerciseOrSupersetId) }

    val overrideSetIndex = remember(isSuperset,currentExercise){
        if(isSuperset){
            currentExercise.sets.filter { it !is RestSet }.indexOf(currentStateSet.set)
        }
        else null
    }

    LaunchedEffect(isNavigationLocked) {
        if (isNavigationLocked) {
            delay(500)
            isNavigationLocked = false
        }
    }

    AnimatedContent(
        modifier = Modifier.fillMaxSize(),
        targetState = selectedExercise,
        transitionSpec = {
            fadeIn(animationSpec = tween(500)) togetherWith fadeOut(animationSpec = tween(500))
        },
        label = "",
    ) { updatedExercise ->
        val updatedExerciseOrSupersetId = if(viewModel.supersetIdByExerciseId.containsKey(updatedExercise.id)) viewModel.supersetIdByExerciseId[updatedExercise.id] else updatedExercise.id
        val updatedExerciseOrSupersetIndex = exerciseOrSupersetIds.indexOf(updatedExerciseOrSupersetId)

        val isSuperset = viewModel.exercisesBySupersetId.containsKey(updatedExerciseOrSupersetId)

        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(5.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 25.dp)
                    .clickable { marqueeEnabled = !marqueeEnabled }
                    .then(if (marqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = updatedExercise.name,
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.title3,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }

            Row(
                modifier = Modifier.height(85.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(5.dp)
            ) {
                if (exerciseIds.size > 1) {
                    Icon(
                        modifier = Modifier.fillMaxHeight().clickable(enabled = !isNavigationLocked && currentIndex > 0) {
                            currentIndex--
                            selectedExercise = viewModel.exercisesById[exerciseIds[currentIndex]]!!
                            isNavigationLocked = true
                        },
                        imageVector = Icons.Filled.ArrowBack,
                        contentDescription = "Previous",
                        tint = if (currentIndex > 0) Color.White else MyColors.MediumGray
                    )
                }

                ExerciseSetsViewer(
                    modifier =  Modifier.fillMaxHeight().weight(1f),
                    viewModel = viewModel,
                    exercise = updatedExercise,
                    currentSet = currentStateSet.set,
                    customColor =   when{
                        updatedExerciseOrSupersetIndex < currentExerciseOrSupersetIndex -> MyColors.Orange
                        updatedExerciseOrSupersetIndex > currentExerciseOrSupersetIndex -> MyColors.MediumGray
                        else -> null
                    },
                    overrideSetIndex = if(updatedExerciseOrSupersetIndex == currentExerciseOrSupersetIndex) {
                        overrideSetIndex
                    }
                    else null
                )

                if (exerciseIds.size > 1) {
                    Icon(
                        modifier = Modifier.fillMaxHeight().clickable(enabled = !isNavigationLocked && currentIndex < exerciseIds.size - 1) {
                            currentIndex++
                            selectedExercise = viewModel.exercisesById[exerciseIds[currentIndex]]!!
                            isNavigationLocked = true
                        },
                        imageVector = Icons.Filled.ArrowForward,
                        contentDescription = "Next",
                        tint = if (currentIndex < exerciseIds.size - 1) Color.White else MyColors.MediumGray
                    )
                }
            }


            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center
            ) {
                Text(
                    textAlign = TextAlign.Center,
                    text = "${updatedExerciseOrSupersetIndex + 1}/${exerciseOrSupersetIds.size}",
                    style = captionStyle
                )
                if(isSuperset){
                    Spacer(modifier = Modifier.width(5.dp))

                    val supersetExercises = remember { viewModel.exercisesBySupersetId[updatedExerciseOrSupersetId]!!  }
                    val supersetIndex = remember { supersetExercises.indexOf(updatedExercise) }

                    Text(
                        textAlign = TextAlign.Center,
                        text = "${supersetIndex + 1}/${supersetExercises.size}",
                        style = captionStyle
                    )
                }
            }
        }
    }
}

@Composable
fun PageButtons(
    updatedState: WorkoutState.Set,
    viewModel: AppViewModel
) {
    val isHistoryEmpty by viewModel.isHistoryEmpty.collectAsState()

    val context = LocalContext.current

    var showGoBackDialog by remember { mutableStateOf(false) }
    val listState = rememberScalingLazyListState(initialCenterItemIndex = 0)

    val exercise = viewModel.exercisesById[updatedState.exerciseId]!!
    val exerciseSets = exercise.sets

    val setIndex = exerciseSets.indexOfFirst { it === updatedState.set }
    val isLastSet = setIndex == exerciseSets.size - 1

    val isMovementSet = updatedState.set is WeightSet || updatedState.set is BodyWeightSet
    val nextWorkoutState by viewModel.nextWorkoutState.collectAsState()

    LaunchedEffect(updatedState) {
        showGoBackDialog = false
    }

    ScalingLazyColumn(
        modifier = Modifier
            .fillMaxSize(),
        state = listState
    ) {
        item {
            ButtonWithText(
                text = "Back",
                onClick = {
                    VibrateGentle(context)
                    showGoBackDialog = true
                },
                enabled = !isHistoryEmpty,
                backgroundColor = MaterialTheme.colors.background
        )
        }
        item {
            val dimmingEnabled by viewModel.enableScreenDimming
            ButtonWithText(
                text = if (dimmingEnabled) "Disable Dimming" else "Enable Dimming",
                onClick = {
                    VibrateGentle(context)
                    viewModel.toggleScreenDimming()
                },
                backgroundColor = if (dimmingEnabled) 
                    MaterialTheme.colors.background
                else
                    MaterialTheme.colors.primary
            )
        }
        if (isMovementSet) {
            item {
                ButtonWithText(
                    text = "Add Set",
                    onClick = {
                        VibrateGentle(context)
                        viewModel.storeSetData()
                        viewModel.pushAndStoreWorkoutData(false, context) {
                            viewModel.addNewSetStandard()
                        }
                    },
                    backgroundColor = MaterialTheme.colors.background
                )
            }
        }
        if (nextWorkoutState !is WorkoutState.Rest) {
            item {
                ButtonWithText(
                    text = "Add Rest",
                    onClick = {
                        VibrateGentle(context)
                        viewModel.storeSetData()
                        viewModel.pushAndStoreWorkoutData(false, context) {
                            viewModel.addNewRest()
                        }
                    },
                    backgroundColor = MaterialTheme.colors.background
                )
            }
        }

        if (isMovementSet && isLastSet) {
            item {
                ButtonWithText(
                    text = "Add Rest-Pause Set",
                    onClick = {
                        VibrateGentle(context)
                        viewModel.storeSetData()
                        viewModel.pushAndStoreWorkoutData(false, context) {
                            viewModel.addNewRestPauseSet()
                        }
                    },
                    backgroundColor = MaterialTheme.colors.background
                )
            }
        }
    }

    CustomDialogYesOnLongPress(
        show = showGoBackDialog,
        title = "Go to previous Set",
        message = "Do you want to proceed?",
        handleYesClick = {
            VibrateGentle(context)
            viewModel.goToPreviousSet()
            viewModel.lightScreenUp()
            showGoBackDialog = false
        },
        handleNoClick = {
            showGoBackDialog = false
            VibrateGentle(context)
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showGoBackDialog = false
        },
        holdTimeInMillis = 1000
    )
}

@Preview(
    device = Devices.WEAR_OS_LARGE_ROUND,
    backgroundColor = 0xFF000000,
    showBackground = true
)
@Composable
fun ExerciseScreenPreview() {
    val viewModel = remember { FakeExerciseScreenAppViewModel() }
    val exerciseState = viewModel.createFakeSetState()
    
    ExerciseScreen(
        viewModel = viewModel,
        state = exerciseState,
        hearthRateChart = { }
    )
}

// Fake classes for preview
private class FakeExerciseScreenAppViewModel : AppViewModel() {
    private val upcomingExerciseId = UUID.randomUUID()
    private val upcomingSetId = UUID.randomUUID()

    fun createFakeSetState(): WorkoutState.Set {
        val exerciseId = upcomingExerciseId
        val weightSet = WeightSet(
            id = upcomingSetId,
            weight = 100.0,
            reps = 10
        )
        
        return WorkoutState.Set(
            set = weightSet,
            exerciseId = exerciseId,
            startTime = null,
            currentSetData = WeightSetData(
                actualWeight = 100.0,
                actualReps = 10,
                volume = 1000.0
            ),
            previousSetData= WeightSetData(
                actualWeight = 100.0,
                actualReps = 10,
                volume = 1000.0
            ),
            plateChangeResult = null,
            order = 1u,
            hasNoHistory = true,
            skipped = false,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 65.0,
            streak = 1,
            isDeloading = false,
            lastSessionVolume = 1000.0,
            expectedProgress = null
        )
    }

    override val allWorkoutStates: MutableList<WorkoutState> = mutableListOf(
        WorkoutState.Set(
            set = WeightSet(
                id = upcomingSetId,
                weight = 100.0,
                reps = 10
            ),
            exerciseId = upcomingExerciseId,
            startTime = null,
            currentSetData = WeightSetData(
                actualWeight = 100.0,
                actualReps = 10,
                volume = 1000.0
            ),
            previousSetData = null,
            plateChangeResult = null,
            order = 1u,
            hasNoHistory = true,
            skipped = false,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 65.0,
            streak = 1,
            isDeloading = false,
            lastSessionVolume = 1000.0,
            expectedProgress = null
        ),
        WorkoutState.Set(
            set = WeightSet(
                id = upcomingSetId,
                weight = 100.0,
                reps = 10
            ),
            exerciseId = upcomingExerciseId,
            startTime = null,
            currentSetData = WeightSetData(
                actualWeight = 100.0,
                actualReps = 10,
                volume = 1000.0
            ),
            previousSetData = null,
            plateChangeResult = null,
            order = 1u,
            hasNoHistory = true,
            skipped = false,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 65.0,
            streak = 1,
            isDeloading = false,
            lastSessionVolume = 1000.0,
            expectedProgress = null
        ),
        WorkoutState.Set(
            set = WeightSet(
                id = upcomingSetId,
                weight = 100.0,
                reps = 10
            ),
            exerciseId = upcomingExerciseId,
            startTime = null,
            currentSetData = WeightSetData(
                actualWeight = 100.0,
                actualReps = 10,
                volume = 1000.0
            ),
            previousSetData = null,
            plateChangeResult = null,
            order = 1u,
            hasNoHistory = true,
            skipped = false,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 65.0,
            streak = 1,
            isDeloading = false,
            lastSessionVolume = 1000.0,
            expectedProgress = null
        ),
        WorkoutState.Set(
            set = WeightSet(
                id = upcomingSetId,
                weight = 100.0,
                reps = 10
            ),
            exerciseId = upcomingExerciseId,
            startTime = null,
            currentSetData = WeightSetData(
                actualWeight = 100.0,
                actualReps = 10,
                volume = 1000.0
            ),
            previousSetData = null,
            plateChangeResult = null,
            order = 1u,
            hasNoHistory = true,
            skipped = false,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 65.0,
            streak = 1,
            isDeloading = false,
            lastSessionVolume = 1000.0,
            expectedProgress = null
        ),
        WorkoutState.Set(
            set = WeightSet(
                id = upcomingSetId,
                weight = 100.0,
                reps = 10
            ),
            exerciseId = upcomingExerciseId,
            startTime = null,
            currentSetData = WeightSetData(
                actualWeight = 100.0,
                actualReps = 10,
                volume = 1000.0
            ),
            previousSetData = null,
            plateChangeResult = null,
            order = 1u,
            hasNoHistory = true,
            skipped = false,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 65.0,
            streak = 1,
            isDeloading = false,
            lastSessionVolume = 1000.0,
            expectedProgress = null
        )
    )

    override val exercisesById = mutableMapOf<UUID, Exercise>().apply {
        put(upcomingExerciseId, Exercise(
            id = upcomingExerciseId,
            name = "Bench Press Preview",
            equipmentId = null,
            notes = "Sample exercise for preview",
            exerciseType = ExerciseType.WEIGHT,
            sets = listOf(
                WeightSet(
                    id = UUID.randomUUID(),
                    weight = 100.0,
                    reps = 10
                )
            ),
            enabled = true,
            doNotStoreHistory = false,
            minLoadPercent = 0.6,
            maxLoadPercent = .8,
            minReps = 6,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            bodyWeightPercentage = null
        ))
    }
    
    override val isPaused = mutableStateOf(false)
    override val isCustomDialogOpen = MutableStateFlow(false)
}

@Composable
fun PageExerciseDetail(
    updatedState: WorkoutState.Set,
    viewModel: AppViewModel,
    onScrollEnabledChange: (Boolean) -> Unit,
    exerciseTitleComposable: @Composable () -> Unit,
    extraInfoComposable: @Composable (WorkoutState.Set) -> Unit
) {
    /*val extraInfoComposable: @Composable (WorkoutState.Set) -> Unit = {state ->
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.Center
        ){
            when (val set = state.set) {
                is WeightSet -> WeightSetDataViewerMinimal(state.previousSetData as WeightSetData,MaterialTheme.typography.caption3)
                is BodyWeightSet -> BodyWeightSetDataViewerMinimal(state.previousSetData as BodyWeightSetData,MaterialTheme.typography.caption2)
                is TimedDurationSet -> TimedDurationSetDataViewerMinimal(state.previousSetData as TimedDurationSetData,MaterialTheme.typography.caption2,historyMode = true)
                is EnduranceSet -> EnduranceSetDataViewerMinimal(state.previousSetData as EnduranceSetData,MaterialTheme.typography.caption2,historyMode = true)
                is RestSet -> throw IllegalStateException("Rest set should not be here")
            }
        }
    }*/

    if (updatedState.set is RestSet || updatedState.currentSetData is RestSetData || updatedState.previousSetData is RestSetData) {
        throw IllegalStateException("Rest set should not be here")
    }

    ExerciseDetail(
        updatedState = updatedState,
        viewModel = viewModel,
        onEditModeDisabled = { onScrollEnabledChange(true) },
        onEditModeEnabled = { onScrollEnabledChange(false) },
        onTimerDisabled = { },
        onTimerEnabled = { },
        extraInfo = extraInfoComposable,
        exerciseTitleComposable = exerciseTitleComposable
    )
}

@Composable
fun PageNotes(notes: String) {
    val scrollState = rememberScrollState()
    Box(
        modifier = Modifier
            .fillMaxSize()
    ) {
        Text(
            modifier = Modifier.fillMaxSize(),
            text = "Notes",
            style = MaterialTheme.typography.title3,
            textAlign = TextAlign.Center
        )

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 25.dp)
                .verticalScroll(scrollState)
        ) {
            Text(
                text = notes.ifEmpty { "NOT AVAILABLE" },
                modifier = Modifier.fillMaxWidth(),
                style = MaterialTheme.typography.body1,
                textAlign = TextAlign.Center
            )
        }
    }
}

@Composable
fun PagePlates(updatedState: WorkoutState.Set, equipment: Equipment?) {
    val scrollState = rememberScrollState()
    Column(
        modifier = Modifier.fillMaxSize(),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            modifier = Modifier.fillMaxWidth(),
            text = "Plates",
            style = MaterialTheme.typography.title3,
            textAlign = TextAlign.Center
        )
        Spacer(modifier = Modifier.height(10.dp))

        if (equipment == null || equipment !is Barbell || updatedState.plateChangeResult == null) {
            Text(
                text = "NOT AVAILABLE",
                style = MaterialTheme.typography.body1,
                textAlign = TextAlign.Center
            )
        } else {
            if (updatedState.plateChangeResult!!.change.steps.isEmpty()) {
                Text(
                    text = "No changes needed",
                    modifier = Modifier.fillMaxWidth(),
                    style = MaterialTheme.typography.body1,
                    textAlign = TextAlign.Center
                )
            } else {
                val typography = MaterialTheme.typography
                val headerStyle =
                    remember { typography.body1.copy(fontSize = typography.body1.fontSize * 0.625f) }

                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(horizontal = 10.dp)
                        .padding(bottom = 10.dp),
                    verticalArrangement = Arrangement.spacedBy(5.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            modifier = Modifier.weight(1f),
                            text = "#",
                            style = headerStyle,
                            textAlign = TextAlign.Center
                        )
                        Text(
                            modifier = Modifier.weight(1f),
                            text = "PLATES",
                            style = headerStyle,
                            textAlign = TextAlign.Center
                        )
                    }

                    if (updatedState.plateChangeResult!!.change.steps.isNotEmpty()) {
                        val style = MaterialTheme.typography.body1

                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .verticalColumnScrollbar(
                                    scrollState = scrollState,
                                    scrollBarColor = Color.White,
                                    scrollBarTrackColor = Color.DarkGray
                                )
                                .verticalScroll(scrollState),
                            verticalArrangement = Arrangement.spacedBy(5.dp),
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            updatedState.plateChangeResult!!.change.steps.forEachIndexed { index, step ->
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Text(
                                        modifier = Modifier.weight(1f),
                                        text = "${index + 1}",
                                        style = MaterialTheme.typography.body1,
                                        textAlign = TextAlign.Center
                                    )
                                    val weightText = if (step.weight % 1 == 0.0) {
                                        "${step.weight.toInt()}"
                                    } else {
                                        "${step.weight}"
                                    }

                                    val actionText =
                                        if (step.action == PlateCalculator.Companion.Action.ADD) {
                                            "+"
                                        } else {
                                            "-"
                                        }

                                    Text(
                                        modifier = Modifier.weight(1f),
                                        text = "$actionText $weightText",
                                        style = style,
                                        textAlign = TextAlign.Center,
                                    )
                                }
                            }
                        }

                    }
                }
            }
        }
    }
}

enum class PageType {
    PLATES, EXERCISE_DETAIL, EXERCISES, NOTES, BUTTONS
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun ExerciseScreen(
    viewModel: AppViewModel,
    state: WorkoutState.Set,
    hearthRateChart: @Composable () -> Unit,
) {
    var allowHorizontalScrolling by remember { mutableStateOf(true) }
    val showNextDialog by viewModel.isCustomDialogOpen.collectAsState()

    val exercise = remember(state.exerciseId) {
        viewModel.exercisesById[state.exerciseId]!!
    }

    val equipment = remember(exercise) {
        exercise.equipmentId?.let { viewModel.getEquipmentById(it) }
    }

    val showPlatesPage = remember(exercise, equipment) {
        equipment != null
                && equipment.type == EquipmentType.BARBELL
                && equipment.name.contains("barbell", ignoreCase = true)
                && (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT)
    }

    val showNotesPage = remember(exercise) {
        exercise.notes.isNotEmpty()
    }

    val pageTypes = remember(showPlatesPage, showNotesPage) {
        mutableListOf<PageType>().apply {
            if (showPlatesPage) add(PageType.PLATES)
            add(PageType.EXERCISE_DETAIL)
            add(PageType.EXERCISES)
            if (showNotesPage) add(PageType.NOTES)
            add(PageType.BUTTONS)
        }
    }

    // Find index of exercise detail page to scroll to on changes
    val exerciseDetailPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.EXERCISE_DETAIL).coerceAtLeast(0)
    }

    val pagerState = rememberPagerState(
        initialPage = exerciseDetailPageIndex,
        pageCount = {
            pageTypes.size
        }
    )

    LaunchedEffect(state.set.id) {
        // Navigate to the exercise detail page
        pagerState.scrollToPage(exerciseDetailPageIndex)
        allowHorizontalScrolling = true
        viewModel.closeCustomDialog()
    }

    LaunchedEffect(allowHorizontalScrolling, pageTypes) {
        if (!allowHorizontalScrolling && pageTypes.getOrNull(pagerState.currentPage) == PageType.PLATES) {
            pagerState.scrollToPage(exerciseDetailPageIndex)
        }
    }

    var marqueeEnabled by remember { mutableStateOf(false) }

    val typography = MaterialTheme.typography
    val captionStyle = remember { typography.body1.copy(fontSize = typography.body1.fontSize * 0.625f) }

    val exerciseOrSupersetIds = remember { viewModel.setsByExerciseId.keys.toList().map { if(viewModel.supersetIdByExerciseId.containsKey(it)) viewModel.supersetIdByExerciseId[it] else it }.distinct() }
    val exerciseOrSupersetId = remember(exercise) { if(viewModel.supersetIdByExerciseId.containsKey(exercise.id)) viewModel.supersetIdByExerciseId[exercise.id] else exercise.id }
    val currentExerciseOrSupersetIndex = remember(exerciseOrSupersetId) { exerciseOrSupersetIds.indexOf(exerciseOrSupersetId) }
    val isSuperset =  remember(exerciseOrSupersetId) { viewModel.exercisesBySupersetId.containsKey(exerciseOrSupersetId) }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(5.dp)
            .circleMask(),
        contentAlignment = Alignment.Center
    ) {
        AnimatedContent(
            targetState = state,
            transitionSpec = {
                fadeIn(animationSpec = tween(500)) togetherWith fadeOut(animationSpec = tween(500))
            }, label = ""
        ) { updatedState ->
            val exerciseSets = remember(updatedState) {  exercise.sets.filter { it !is RestSet }}
            val setIndex = remember(updatedState) { exerciseSets.indexOf(updatedState.set)  }

            val exerciseTitleComposable = @Composable {
                Column(modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 30.dp),
                    verticalArrangement = Arrangement.spacedBy(5.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { marqueeEnabled = !marqueeEnabled }
                            .then(if (marqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier),
                        text = exercise.name,
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.title3,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
            }

            CustomHorizontalPager(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(top = 5.dp)
                    .padding(vertical = 20.dp, horizontal = 15.dp),
                pagerState = pagerState,
                userScrollEnabled = allowHorizontalScrolling,
            ) { pageIndex ->
                // Get the page type for the current index
                val pageType = pageTypes[pageIndex]

                when (pageType) {
                    PageType.PLATES -> PagePlates(updatedState, equipment)
                    PageType.EXERCISE_DETAIL -> PageExerciseDetail(
                        updatedState = updatedState,
                        viewModel = viewModel,
                        onScrollEnabledChange = {
                            allowHorizontalScrolling = it
                        },
                        exerciseTitleComposable = exerciseTitleComposable,
                        extraInfoComposable = { _ ->
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.Center
                            ){
                                Row(horizontalArrangement = Arrangement.spacedBy(5.dp)){
                                    Text(
                                        textAlign = TextAlign.Center,
                                        text =  "${currentExerciseOrSupersetIndex + 1}/${exerciseOrSupersetIds.size}",
                                        style = captionStyle
                                    )
                                    if(isSuperset){
                                        val supersetExercises = viewModel.exercisesBySupersetId[exerciseOrSupersetId]!!
                                        val supersetIndex = supersetExercises.indexOf(exercise)

                                        Text(
                                            textAlign = TextAlign.Center,
                                            text =  "${supersetIndex + 1}/${supersetExercises.size}",
                                            style = captionStyle
                                        )
                                    }
                                    Text(
                                        textAlign = TextAlign.Center,
                                        text =  "${setIndex + 1}/${exerciseSets.size}",
                                        style = captionStyle
                                    )
                                }
                            }
                        }
                    )
                    PageType.EXERCISES -> PageExercises(updatedState, viewModel, exercise)
                    PageType.NOTES -> PageNotes(exercise.notes)
                    PageType.BUTTONS -> PageButtons(updatedState, viewModel)
                }
            }
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        ExerciseIndicator(
            modifier = Modifier.fillMaxSize(),
            viewModel,
            state
        )

        hearthRateChart()
    }

    val context = LocalContext.current

    CustomDialogYesOnLongPress(
        show = showNextDialog,
        title = "Complete Set",
        message = "Do you want to proceed?",
        handleYesClick = {
            VibrateGentle(context)
            viewModel.storeSetData()
            viewModel.pushAndStoreWorkoutData(false, context) {
                viewModel.upsertWorkoutRecord(state.set.id)
                viewModel.goToNextState()
                viewModel.lightScreenUp()
            }

            viewModel.closeCustomDialog()
        },
        handleNoClick = {
            viewModel.closeCustomDialog()
            VibrateGentle(context)
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            viewModel.closeCustomDialog()
        },
        holdTimeInMillis = 1000
    )
}
