package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.HapticsHelper
import com.gabstra.myworkoutassistant.ui.theme.MyWorkoutAssistantTheme
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.ExerciseChildItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateContainer
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateMachine
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceItem
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.flow.MutableStateFlow
import java.util.UUID

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun PageExercises(
    workoutState: WorkoutState?,
    viewModel: WorkoutViewModel,
    hapticsViewModel: HapticsViewModel,
    currentExercise: Exercise,
    onExerciseSelected: (UUID) -> Unit,
) {
    val exerciseOrSupersetIds = remember(viewModel.allWorkoutStates.size) {
        viewModel.setsByExerciseId.keys
            .map { exerciseId -> viewModel.supersetIdByExerciseId[exerciseId] ?: exerciseId }
            .distinct()
    }
    val currentExerciseOrSupersetId = remember(currentExercise.id) {
        viewModel.supersetIdByExerciseId[currentExercise.id] ?: currentExercise.id
    }
    val currentStepIndex = exerciseOrSupersetIds.indexOf(currentExerciseOrSupersetId)
        .coerceAtLeast(0)
    var selectedStepIndex by remember(currentExercise.id, exerciseOrSupersetIds) {
        mutableStateOf(currentStepIndex)
    }

    fun representativeExercise(stepIndex: Int): Exercise? {
        val stepId = exerciseOrSupersetIds.getOrNull(stepIndex) ?: return null
        return viewModel.exercisesBySupersetId[stepId]?.firstOrNull()
            ?: viewModel.exercisesById[stepId]
    }

    val selectedExercise = representativeExercise(selectedStepIndex) ?: currentExercise
    val selectedStepId = exerciseOrSupersetIds.getOrNull(selectedStepIndex)
    val selectedSupersetExercises = selectedStepId?.let(viewModel.exercisesBySupersetId::get)
    val selectedTitle = selectedSupersetExercises
        ?.joinToString(separator = " + ") { exercise -> exercise.name }
        ?: selectedExercise.name

    LaunchedEffect(selectedExercise.id) {
        onExerciseSelected(selectedExercise.id)
    }

    val currentSet = remember(workoutState, selectedExercise.id) {
        when (workoutState) {
            is WorkoutState.Set -> workoutState.set
            is WorkoutState.Rest -> workoutState.set
            is WorkoutState.CalibrationLoadSelection -> workoutState.calibrationSet
            is WorkoutState.CalibrationRIRSelection -> workoutState.calibrationSet
            is WorkoutState.AutoRegulationRIRSelection -> workoutState.workSet
            else -> selectedExercise.sets.firstOrNull()
        }
    }
    Column(
        modifier = Modifier
            .fillMaxSize()
            .graphicsLayer()
            .padding(horizontal = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(bottom = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = selectedTitle,
                modifier = Modifier
                    .fillMaxWidth()
                    .basicMarquee(iterations = Int.MAX_VALUE),
                maxLines = 1,
                softWrap = false,
                overflow = TextOverflow.Clip,
                style = MaterialTheme.typography.headlineMedium.copy(fontWeight = FontWeight.SemiBold),
                textAlign = TextAlign.Center,
            )
        }

        if (currentSet != null) {
            ExerciseSetsViewer(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                viewModel = viewModel,
                hapticsViewModel = hapticsViewModel,
                exercise = selectedExercise,
                currentSet = currentSet,
                customMarkAsDone = when {
                    selectedStepIndex < currentStepIndex -> true
                    selectedStepIndex > currentStepIndex -> false
                    else -> null
                },
                customBorderColor = null,
                customTextColor = null,
                isFutureExercise = selectedStepIndex > currentStepIndex,
            )
        } else {
            Box(modifier = Modifier.weight(1f))
        }

        if (exerciseOrSupersetIds.isNotEmpty()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 20.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                StepNavigationButton(
                    enabled = selectedStepIndex > 0,
                    forward = false,
                    onClick = {
                        hapticsViewModel.doGentleVibration()
                        selectedStepIndex -= 1
                    },
                )
                Text(
                    text = "Step: ${selectedStepIndex + 1}/${exerciseOrSupersetIds.size}",
                    modifier = Modifier.weight(1f),
                    style = MaterialTheme.typography.titleMedium.copy(
                        fontSize = 18.sp,
                        lineHeight = 22.sp,
                        fontWeight = FontWeight.SemiBold,
                    ),
                    color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.78f),
                    textAlign = TextAlign.Center,
                )
                StepNavigationButton(
                    enabled = selectedStepIndex < exerciseOrSupersetIds.lastIndex,
                    forward = true,
                    onClick = {
                        hapticsViewModel.doGentleVibration()
                        selectedStepIndex += 1
                    },
                )
            }
        }
    }
}

@Composable
private fun StepNavigationButton(
    enabled: Boolean,
    forward: Boolean,
    onClick: () -> Unit,
) {
    IconButton(
        enabled = enabled,
        onClick = onClick,
        modifier = Modifier
            .size(56.dp)
            .alpha(if (enabled) 1f else 0.35f),
    ) {
        Icon(
            modifier = Modifier.size(32.dp),
            imageVector = if (forward) {
                Icons.AutoMirrored.Filled.ArrowForward
            } else {
                Icons.AutoMirrored.Filled.ArrowBack
            },
            contentDescription = if (forward) "Next step" else "Previous step",
            tint = MaterialTheme.colorScheme.onBackground,
        )
    }
}

private data class MobileExercisesPagePreviewFixture(
    val viewModel: WorkoutViewModel,
    val firstExercise: Exercise,
    val supersetExercise: Exercise,
    val firstSetState: WorkoutState.Set,
    val completedSetState: WorkoutState.Set,
    val supersetSetState: WorkoutState.Set,
    val restState: WorkoutState.Rest,
)

private enum class MobileExercisesPreviewState { NORMAL, REST, DONE, SUPERSET }

private fun previewWeightSet(idSuffix: Int, weight: Double) = WeightSet(
    id = UUID.fromString("82000000-0000-0000-0000-${idSuffix.toString().padStart(12, '0')}"),
    reps = 8,
    weight = weight,
    subCategory = SetSubCategory.WorkSet,
)

private fun previewExercise(idSuffix: Int, name: String, sets: List<com.gabstra.myworkoutassistant.shared.sets.Set>) =
    Exercise(
        id = UUID.fromString("81000000-0000-0000-0000-${idSuffix.toString().padStart(12, '0')}"),
        enabled = true,
        name = name,
        notes = "",
        sets = sets,
        exerciseType = ExerciseType.WEIGHT,
        minReps = 6,
        maxReps = 10,
        lowerBoundMaxHRPercent = null,
        upperBoundMaxHRPercent = null,
        equipmentId = null,
        bodyWeightPercentage = null,
    )

private fun previewSetState(
    exercise: Exercise,
    setIndex: Int,
    weightSet: WeightSet,
) = WorkoutState.Set(
    exerciseId = exercise.id,
    set = weightSet,
    setIndex = setIndex.toUInt(),
    previousSetData = WeightSetData(
        actualReps = 8,
        actualWeight = weightSet.weight - 2.5,
        volume = (weightSet.weight - 2.5) * 8,
    ),
    currentSetDataState = mutableStateOf(
        WeightSetData(
            actualReps = 8,
            actualWeight = weightSet.weight,
            volume = weightSet.weight * 8,
        )
    ),
    hasNoHistory = false,
    skipped = false,
    currentBodyWeight = 0.0,
    streak = 1,
    progressionState = null,
    isWarmupSet = false,
    equipmentId = null,
)

private fun buildMobileExercisesPagePreviewFixture(
    manySets: Boolean = false,
    selectedState: MobileExercisesPreviewState = MobileExercisesPreviewState.NORMAL,
): MobileExercisesPagePreviewFixture {
    val viewModel = WorkoutViewModel()
    val firstWeightSets = if (manySets) {
        (1..18).map { previewWeightSet(it, 60.0 + it) }
    } else {
        listOf(previewWeightSet(1, 80.0), previewWeightSet(2, 82.5), previewWeightSet(3, 82.5))
    }
    val firstExercise = previewExercise(1, if (manySets) "Long Set List" else "Bench Press", firstWeightSets)
    val secondExercise = previewExercise(2, "Barbell Row", listOf(previewWeightSet(20, 60.0)))
    val supersetExercise = previewExercise(3, "Incline Dumbbell Press", listOf(previewWeightSet(30, 24.0)))
    val supersetPartner = previewExercise(4, "One-arm Row", listOf(previewWeightSet(40, 22.0)))
    val firstStates = firstWeightSets.mapIndexed { index, set ->
        previewSetState(firstExercise, index + 1, set)
    }
    val secondState = previewSetState(secondExercise, 1, secondExercise.sets.single() as WeightSet)
    val supersetState = previewSetState(supersetExercise, 1, supersetExercise.sets.single() as WeightSet)
    val supersetPartnerState = previewSetState(
        supersetPartner,
        1,
        supersetPartner.sets.single() as WeightSet,
    )
    val restSet = RestSet(
        id = UUID.fromString("83000000-0000-0000-0000-000000000001"),
        timeInSeconds = 90,
        subCategory = SetSubCategory.WorkSet,
    )
    val restState = WorkoutState.Rest(
        set = restSet,
        order = 2u,
        currentSetDataState = mutableStateOf(RestSetData(startTimer = 90, endTimer = 45)),
        exerciseId = firstExercise.id,
    )
    val supersetId = UUID.fromString("84000000-0000-0000-0000-000000000001")
    val sequence = listOf(
        WorkoutStateSequenceItem.Container(
            WorkoutStateContainer.ExerciseState(
                exerciseId = firstExercise.id,
                childItems = firstStates.map { ExerciseChildItem.Normal(it) }.toMutableList(),
            )
        ),
        WorkoutStateSequenceItem.RestBetweenExercises(restState),
        WorkoutStateSequenceItem.Container(
            WorkoutStateContainer.ExerciseState(
                exerciseId = secondExercise.id,
                childItems = mutableListOf(ExerciseChildItem.Normal(secondState)),
            )
        ),
        WorkoutStateSequenceItem.Container(
            WorkoutStateContainer.SupersetState(
                supersetId = supersetId,
                childStates = mutableListOf(supersetState, supersetPartnerState),
            )
        ),
    )
    viewModel.exercisesById = listOf(firstExercise, secondExercise, supersetExercise, supersetPartner)
        .associateBy(Exercise::id)
    viewModel.supersetIdByExerciseId = mapOf(
        supersetExercise.id to supersetId,
        supersetPartner.id to supersetId,
    )
    viewModel.exercisesBySupersetId = mapOf(supersetId to listOf(supersetExercise, supersetPartner))
    val selectedStateIndex = when (selectedState) {
        MobileExercisesPreviewState.NORMAL -> 0
        MobileExercisesPreviewState.REST -> firstStates.size
        MobileExercisesPreviewState.DONE -> firstStates.lastIndex
        MobileExercisesPreviewState.SUPERSET -> firstStates.size + 2
    }
    setPreviewField(
        viewModel,
        "stateMachine",
        WorkoutStateMachine.fromSequence(sequence, startIndex = selectedStateIndex),
    )

    return MobileExercisesPagePreviewFixture(
        viewModel = viewModel,
        firstExercise = firstExercise,
        supersetExercise = supersetExercise,
        firstSetState = firstStates.first(),
        completedSetState = firstStates.last(),
        supersetSetState = supersetState,
        restState = restState,
    )
}

private fun setPreviewField(target: Any, fieldName: String, value: Any?) {
    findPreviewField(target, fieldName).set(target, value)
}

@Suppress("UNCHECKED_CAST")
private fun setPreviewWorkoutState(viewModel: WorkoutViewModel, state: WorkoutState) {
    val stateFlow = findPreviewField(viewModel, "_workoutState").get(viewModel)
        as? MutableStateFlow<WorkoutState>
    stateFlow?.value = state
}

private fun findPreviewField(target: Any, fieldName: String): java.lang.reflect.Field {
    var type: Class<*>? = target.javaClass
    while (type != null) {
        type.declaredFields.firstOrNull { it.name == fieldName }?.let { field ->
            field.isAccessible = true
            return field
        }
        type = type.superclass
    }
    error("Preview field $fieldName was not found")
}

@Composable
private fun MobileExercisesPagePreviewContent(
    fixture: MobileExercisesPagePreviewFixture,
    exercise: Exercise,
    state: WorkoutState,
) {
    val context = LocalContext.current
    val hapticsViewModel = remember(context) { HapticsViewModel(context, HapticsHelper(context)) }
    setPreviewWorkoutState(fixture.viewModel, state)
    MyWorkoutAssistantTheme {
        PageExercises(
            workoutState = state,
            viewModel = fixture.viewModel,
            hapticsViewModel = hapticsViewModel,
            currentExercise = exercise,
            onExerciseSelected = {},
        )
    }
}

@Preview(name = "Rest Context", group = "Mobile Workout/Exercises", showBackground = true)
@Composable
private fun MobileExercisesPageRestPreview() {
    val fixture = remember {
        buildMobileExercisesPagePreviewFixture(selectedState = MobileExercisesPreviewState.REST)
    }
    MobileExercisesPagePreviewContent(fixture, fixture.firstExercise, fixture.restState)
}

@Preview(name = "Normal Exercise", group = "Mobile Workout/Exercises", showBackground = true)
@Composable
private fun MobileExercisesPageNormalPreview() {
    val fixture = remember { buildMobileExercisesPagePreviewFixture() }
    MobileExercisesPagePreviewContent(fixture, fixture.firstExercise, fixture.firstSetState)
}

@Preview(name = "Done Sets Filled", group = "Mobile Workout/Exercises", showBackground = true)
@Composable
private fun MobileExercisesPageDoneSetsPreview() {
    val fixture = remember {
        buildMobileExercisesPagePreviewFixture(selectedState = MobileExercisesPreviewState.DONE)
    }
    MobileExercisesPagePreviewContent(fixture, fixture.firstExercise, fixture.completedSetState)
}

@Preview(name = "Superset", group = "Mobile Workout/Exercises", showBackground = true)
@Composable
private fun MobileExercisesPageSupersetPreview() {
    val fixture = remember {
        buildMobileExercisesPagePreviewFixture(selectedState = MobileExercisesPreviewState.SUPERSET)
    }
    MobileExercisesPagePreviewContent(fixture, fixture.supersetExercise, fixture.supersetSetState)
}

@Preview(name = "Many Sets Last Selected", group = "Mobile Workout/Exercises", showBackground = true)
@Composable
private fun MobileExercisesPageManySetsPreview() {
    val fixture = remember {
        buildMobileExercisesPagePreviewFixture(
            manySets = true,
            selectedState = MobileExercisesPreviewState.DONE,
        )
    }
    MobileExercisesPagePreviewContent(fixture, fixture.firstExercise, fixture.completedSetState)
}

@Composable
private fun MobileExerciseScreenPreviewContent(
    fixture: MobileExercisesPagePreviewFixture,
    state: WorkoutState.Set,
) {
    val context = LocalContext.current
    val hapticsViewModel = remember(context) { HapticsViewModel(context, HapticsHelper(context)) }
    setPreviewWorkoutState(fixture.viewModel, state)
    MyWorkoutAssistantTheme {
        ExerciseScreen(
            viewModel = fixture.viewModel,
            hapticsViewModel = hapticsViewModel,
            state = state,
            hearthRateChart = {},
        )
    }
}

@Preview(name = "Normal Work Set", group = "Mobile Workout/Exercise Screen", showBackground = true)
@Composable
private fun MobileExerciseScreenNormalPreview() {
    val fixture = remember { buildMobileExercisesPagePreviewFixture() }
    MobileExerciseScreenPreviewContent(fixture, fixture.firstSetState)
}

@Preview(name = "Completed Sets", group = "Mobile Workout/Exercise Screen", showBackground = true)
@Composable
private fun MobileExerciseScreenCompletedSetsPreview() {
    val fixture = remember {
        buildMobileExercisesPagePreviewFixture(selectedState = MobileExercisesPreviewState.DONE)
    }
    MobileExerciseScreenPreviewContent(fixture, fixture.completedSetState)
}

@Preview(name = "Superset Work Set", group = "Mobile Workout/Exercise Screen", showBackground = true)
@Composable
private fun MobileExerciseScreenSupersetPreview() {
    val fixture = remember {
        buildMobileExercisesPagePreviewFixture(selectedState = MobileExercisesPreviewState.SUPERSET)
    }
    MobileExerciseScreenPreviewContent(fixture, fixture.supersetSetState)
}

@Preview(name = "Active Rest", group = "Mobile Workout/Rest Screen", showBackground = true)
@Composable
private fun MobileRestScreenPreview() {
    val fixture = remember {
        buildMobileExercisesPagePreviewFixture(selectedState = MobileExercisesPreviewState.REST)
    }
    val context = LocalContext.current
    val hapticsViewModel = remember(context) { HapticsViewModel(context, HapticsHelper(context)) }
    setPreviewWorkoutState(fixture.viewModel, fixture.restState)
    MyWorkoutAssistantTheme {
        RestScreen(
            viewModel = fixture.viewModel,
            hapticsViewModel = hapticsViewModel,
            state = fixture.restState,
            hearthRateChart = {},
            onTimerEnd = {},
        )
    }
}
