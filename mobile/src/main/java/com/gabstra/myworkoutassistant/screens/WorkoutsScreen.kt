package com.gabstra.myworkoutassistant.screens

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding

import androidx.compose.foundation.layout.wrapContentSize

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.MoreVert

import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.Button

import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.composables.ExpandableCard
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.ExerciseGroupRenderer
import com.gabstra.myworkoutassistant.composables.ExerciseRenderer
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.SelectableList
import com.gabstra.myworkoutassistant.composables.WorkoutRenderer
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup
import com.google.accompanist.permissions.ExperimentalPermissionsApi

@OptIn(ExperimentalPermissionsApi::class)
@Composable
fun Menu(
    onSyncClick: () -> Unit,
    onSaveClick: () -> Unit,
    onOpenSettingsClick: () -> Unit,
    onFileSelected: (Uri) -> Unit
) {
    var expanded by remember { mutableStateOf(false) }

    val launcher = rememberLauncherForActivityResult(contract = ActivityResultContracts.OpenDocument()) { uri: Uri? ->
        uri?.let { onFileSelected(it) }
    }

    Box(
        modifier = Modifier.wrapContentSize(Alignment.TopEnd)
    ) {
        IconButton(onClick = { expanded = !expanded }) {
            Icon(
                imageVector = Icons.Default.MoreVert,
                contentDescription = "More"
            )
        }

        DropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false }
        ) {
            DropdownMenuItem(
                text = { Text("Sync with Watch") },
                onClick = {
                    onSyncClick()
                    expanded = false
                }
            )
            DropdownMenuItem(
                text = { Text("Save") },
                onClick = {
                    onSaveClick()
                    expanded = false
                }
            )
            DropdownMenuItem(
                text = { Text("Settings") },
                onClick = {
                    onOpenSettingsClick()
                    expanded = false
                }
            )
            DropdownMenuItem(
                text = {Text("Load JSON") },
                onClick = {
                    launcher.launch(arrayOf("application/json"))
                    expanded = false
                }
            )
        }
    }
}

@Composable
fun WorkoutTitle(modifier: Modifier,workout: Workout){
    Row (
        horizontalArrangement = Arrangement.SpaceBetween,
        modifier = modifier.padding(15.dp)
    ){
        Text(
            modifier = Modifier.weight(1f),
            text = workout.name
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun WorkoutsScreen(
    appViewModel: AppViewModel,
    onSyncClick: () -> Unit,
    onSaveClick: () -> Unit,
    onOpenSettingsClick: () -> Unit,
    onFileSelected: (Uri) -> Unit
) {
    var workouts by remember { mutableStateOf(appViewModel.workouts) }
    var selectedWorkouts by remember { mutableStateOf(listOf<Workout>()) }
    var isSelectionModeActive by remember { mutableStateOf(false) }

    //add a menu in the floating action button
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("My Workout Assistant") },
                actions = {
                    Menu(
                        onSaveClick = onSaveClick,
                        onSyncClick = onSyncClick,
                        onOpenSettingsClick = onOpenSettingsClick,
                        onFileSelected = onFileSelected
                    )
                }
            )
        },
        bottomBar = {
            if(selectedWorkouts.isNotEmpty()) BottomAppBar(
                actions =  {
                    IconButton(onClick = {
                        val newWorkouts = workouts.filter { workout ->
                            workout !in selectedWorkouts
                        }
                        workouts = newWorkouts
                        appViewModel.updateWorkouts(newWorkouts)
                        selectedWorkouts = emptyList()
                        isSelectionModeActive = false
                    }) {
                        Icon(imageVector = Icons.Default.Delete, contentDescription = "Delete")
                    }
                    Button(
                        modifier = Modifier.padding(5.dp),
                        onClick = {
                            for (workout in selectedWorkouts) {
                                appViewModel.updateWorkout(workout,workout.copy(enabled = true))
                            }
                            selectedWorkouts = emptyList()
                            isSelectionModeActive = false
                        }) {
                        Text("Enable")
                    }
                    Button(
                        modifier = Modifier.padding(5.dp),
                        onClick = {
                            for (workout in selectedWorkouts) {
                                appViewModel.updateWorkout(workout,workout.copy(enabled = false))
                            }
                            selectedWorkouts = emptyList()
                            isSelectionModeActive = false
                        }) {
                        Text("Disable")
                    }
                }
            )
        },
        floatingActionButton= {
            if(selectedWorkouts.isEmpty())
                FloatingActionButton(
                    onClick = {
                        appViewModel.setScreenData(ScreenData.NewWorkout());
                    }
                ) {
                    Icon(
                        imageVector = Icons.Default.Add,
                        contentDescription = null
                    )
                }
        }
    ) {
        if(workouts.isEmpty()){
            Text(modifier = Modifier
                .padding(it)
                .fillMaxSize(),text = "Add a new workout", textAlign = TextAlign.Center)
        }else{
            GenericSelectableList(
                it,
                items = workouts,
                selectedItems= selectedWorkouts,
                isSelectionModeActive,
                onItemClick = {
                    appViewModel.setScreenData(ScreenData.WorkoutDetail(it.id))
                },
                onEnableSelection = { isSelectionModeActive = true },
                onDisableSelection = { isSelectionModeActive = false },
                onSelectionChange = { newSelection -> selectedWorkouts = newSelection} ,
                onOrderChange = { newWorkouts->
                    appViewModel.updateWorkouts(newWorkouts)
                    workouts = newWorkouts
                },
                itemContent = { it ->
                    ExpandableCard(
                        isExpandable = it.workoutComponents.isNotEmpty(),
                        modifier = Modifier
                            .fillMaxWidth()
                            .alpha(if (it.enabled) 1f else 0.4f),
                        title = { modifier ->  WorkoutTitle(modifier,it) },
                        content = { WorkoutRenderer(it) }
                    )
                }
            )
        }
    }
}
