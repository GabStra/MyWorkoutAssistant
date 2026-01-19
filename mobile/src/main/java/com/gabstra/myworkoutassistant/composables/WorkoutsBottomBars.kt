package com.gabstra.myworkoutassistant.composables

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowForward
import androidx.compose.material.icons.filled.Block
import androidx.compose.material.icons.filled.CheckBox
import androidx.compose.material.icons.filled.CheckBoxOutlineBlank
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.ChevronLeft
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.VerticalDivider
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import java.time.LocalDate
import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbells
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.util.UUID

@Composable
fun WorkoutsBottomBar(
    selectedWorkouts: List<Workout>,
    activeWorkouts: List<Workout>,
    appViewModel: AppViewModel,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    scope: CoroutineScope,
    context: Context,
    onSelectionChange: (List<Workout>) -> Unit,
    onSelectionModeChange: (Boolean) -> Unit,
    onShowMoveWorkoutDialogChange: (Boolean) -> Unit,
    onUpdateWorkoutsEnabledState: (Boolean) -> Unit,
    onGroupedWorkoutsHistoriesChange: (Map<java.time.LocalDate, List<WorkoutHistory>>?) -> Unit,
    isSelectionModeActive: Boolean
) {
    if (isSelectionModeActive) {
        Column {
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            BottomAppBar(
                contentPadding = PaddingValues(0.dp),
                containerColor = Color.Transparent,
                actions = {
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
                                    modifier = Modifier.width(56.dp)
                                ) {
                                    IconButton(onClick = {
                                        onSelectionChange(emptyList())
                                        onSelectionModeChange(false)
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
                                    modifier = Modifier.width(56.dp)
                                ) {
                                    IconButton(onClick = {
                                        onSelectionChange(activeWorkouts)
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
                                    modifier = Modifier.width(56.dp)
                                ) {
                                    IconButton(onClick = {
                                        onSelectionChange(emptyList())
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
                                    modifier = Modifier.width(56.dp)
                                ) {
                                    IconButton(
                                        onClick = {
                                            appViewModel.deleteWorkouts(selectedWorkouts.map { it.id }.toSet())
                                            appViewModel.scheduleWorkoutSave(context)
                                            scope.launch(Dispatchers.IO) {
                                                for (workout in selectedWorkouts) {
                                                    val workoutHistories =
                                                        workoutHistoryDao.getWorkoutsByWorkoutId(workout.id)
                                                    for (workoutHistory in workoutHistories) {
                                                        setHistoryDao.deleteByWorkoutHistoryId(workoutHistory.id)
                                                    }
                                                    workoutHistoryDao.deleteAllByWorkoutId(workout.id)
                                                }
                                                val groupedHistories =
                                                    workoutHistoryDao.getAllWorkoutHistories()
                                                        .groupBy { it.date }
                                                onGroupedWorkoutsHistoriesChange(groupedHistories)
                                            }
                                            onSelectionChange(emptyList())
                                            onSelectionModeChange(false)
                                        }
                                    ) {
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
                                Column(
                                    horizontalAlignment = Alignment.CenterHorizontally,
                                    modifier = Modifier.width(56.dp)
                                ) {
                                    IconButton(
                                        onClick = {
                                            onUpdateWorkoutsEnabledState(true)
                                        },
                                        colors = IconButtonDefaults.iconButtonColors(
                                            contentColor = MaterialTheme.colorScheme.onBackground,
                                            disabledContentColor = DisabledContentGray
                                        )
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
                                Column(
                                    horizontalAlignment = Alignment.CenterHorizontally,
                                    modifier = Modifier.width(56.dp)
                                ) {
                                    IconButton(
                                        onClick = {
                                            onUpdateWorkoutsEnabledState(false)
                                        },
                                        colors = IconButtonDefaults.iconButtonColors(
                                            contentColor = MaterialTheme.colorScheme.onBackground,
                                            disabledContentColor = DisabledContentGray
                                        )
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
                                Column(
                                    horizontalAlignment = Alignment.CenterHorizontally,
                                    modifier = Modifier.width(56.dp)
                                ) {
                                    IconButton(
                                        onClick = {
                                            onShowMoveWorkoutDialogChange(true)
                                        }
                                    ) {
                                        Icon(
                                            imageVector = Icons.Filled.ArrowForward,
                                            contentDescription = "Move",
                                            tint = MaterialTheme.colorScheme.onBackground
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
    }
}

@Composable
fun AccessoriesBottomBar(
    selectedAccessories: List<AccessoryEquipment>,
    accessories: List<AccessoryEquipment>,
    appViewModel: AppViewModel,
    onSelectionChange: (List<AccessoryEquipment>) -> Unit,
    onSelectionModeChange: (Boolean) -> Unit,
    isSelectionModeActive: Boolean
) {
    if (isSelectionModeActive) {
        Column {
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            BottomAppBar(
                contentPadding = PaddingValues(0.dp),
                containerColor = Color.Transparent,
                actions = {
                    Row(
                        modifier = Modifier.fillMaxSize(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.Top
                    ) {
                        Column(
                            horizontalAlignment = Alignment.CenterHorizontally,
                            modifier = Modifier.width(56.dp)
                        ) {
                            IconButton(onClick = {
                                onSelectionChange(emptyList())
                                onSelectionModeChange(false)
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
                                textAlign = TextAlign.Center
                            )
                        }
                        Column(
                            horizontalAlignment = Alignment.CenterHorizontally,
                            modifier = Modifier.width(56.dp)
                        ) {
                            IconButton(onClick = {
                                onSelectionChange(accessories)
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
                            modifier = Modifier.width(56.dp)
                        ) {
                            IconButton(onClick = {
                                onSelectionChange(emptyList())
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
                            modifier = Modifier.width(56.dp)
                        ) {
                            IconButton(onClick = {
                                val newAccessories = accessories.filter { item ->
                                    selectedAccessories.none { it.id == item.id }
                                }
                                appViewModel.updateAccessoryEquipments(newAccessories)
                                onSelectionModeChange(false)
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
                    }
                }
            )
        }
    }
}

@Composable
fun EquipmentsBottomBar(
    selectedEquipments: List<WeightLoadedEquipment>,
    equipments: List<WeightLoadedEquipment>,
    appViewModel: AppViewModel,
    onSelectionChange: (List<WeightLoadedEquipment>) -> Unit,
    onSelectionModeChange: (Boolean) -> Unit,
    isSelectionModeActive: Boolean
) {
    if (isSelectionModeActive) {
        Column {
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            BottomAppBar(
                contentPadding = PaddingValues(0.dp),
                containerColor = Color.Transparent,
                actions = {
                    Row(
                        modifier = Modifier.fillMaxSize(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.Top
                    ) {
                        Column(
                            horizontalAlignment = Alignment.CenterHorizontally,
                            modifier = Modifier.width(56.dp)
                        ) {
                            IconButton(onClick = {
                                onSelectionChange(emptyList())
                                onSelectionModeChange(false)
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
                            modifier = Modifier.width(56.dp)
                        ) {
                            IconButton(onClick = {
                                onSelectionChange(equipments)
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
                            modifier = Modifier.width(56.dp)
                        ) {
                            IconButton(onClick = {
                                onSelectionChange(emptyList())
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
                            modifier = Modifier.width(56.dp)
                        ) {
                            IconButton(onClick = {
                                val newEquipments = selectedEquipments.map { it ->
                                    when (it.type) {
                                        EquipmentType.GENERIC -> throw NotImplementedError()
                                        EquipmentType.BARBELL -> Barbell(
                                            id = UUID.randomUUID(),
                                            name = it.name + " (Copy)",
                                            availablePlates = (it as Barbell).availablePlates,
                                            sleeveLength = it.sleeveLength,
                                            barWeight = it.barWeight
                                        )
                                        EquipmentType.DUMBBELLS -> Dumbbells(
                                            UUID.randomUUID(),
                                            it.name + " (Copy)",
                                            (it as Dumbbells).availableDumbbells,
                                            it.extraWeights,
                                            it.maxExtraWeightsPerLoadingPoint
                                        )
                                        EquipmentType.DUMBBELL -> TODO()
                                        EquipmentType.PLATELOADEDCABLE -> TODO()
                                        EquipmentType.WEIGHTVEST -> TODO()
                                        EquipmentType.MACHINE -> TODO()
                                        EquipmentType.IRONNECK -> TODO()
                                        EquipmentType.ACCESSORY -> throw IllegalArgumentException("Accessories cannot be copied here")
                                    }
                                }

                                val newTotalEquipments = equipments + newEquipments

                                appViewModel.updateEquipments(newTotalEquipments)
                                onSelectionModeChange(false)
                            }) {
                                Icon(
                                    imageVector = Icons.Default.ContentCopy,
                                    contentDescription = "Copy",
                                    tint = MaterialTheme.colorScheme.onBackground
                                )
                            }
                            Text(
                                "Copy",
                                style = MaterialTheme.typography.labelSmall,
                                textAlign = TextAlign.Center
                            )
                        }
                        Column(
                            horizontalAlignment = Alignment.CenterHorizontally,
                            modifier = Modifier.width(56.dp)
                        ) {
                            IconButton(onClick = {
                                val newEquipments = equipments.filter { item ->
                                    selectedEquipments.none { it.id == item.id }
                                }
                                appViewModel.updateEquipments(newEquipments)
                                onSelectionModeChange(false)
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
                    }
                }
            )
        }
    }
}
