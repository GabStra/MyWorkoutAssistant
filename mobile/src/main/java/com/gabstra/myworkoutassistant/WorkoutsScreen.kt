package com.gabstra.myworkoutassistant

import android.Manifest.permission.READ_EXTERNAL_STORAGE
import android.content.pm.PackageManager
import android.net.Uri
import android.util.Log
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding

import androidx.compose.foundation.layout.wrapContentSize

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.MoreVert

import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults

import androidx.compose.material3.Divider
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.navigation.NavController
import com.gabstra.myworkoutassistant.shared.Workout
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import com.google.accompanist.permissions.PermissionStatus
import com.google.accompanist.permissions.isGranted
import com.google.accompanist.permissions.rememberPermissionState
import com.google.accompanist.permissions.shouldShowRationale

@OptIn(ExperimentalPermissionsApi::class)
@Composable
fun Menu(
    onSyncClick: () -> Unit,
    onSaveClick: () -> Unit,
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
        Text(
            text = "(${workout.exerciseGroups.size.toString()})"
        )
    }
}

@Composable
fun WorkoutContent(workout: Workout){
    Card(
        modifier=Modifier.padding(15.dp)
       ){
        Spacer(modifier=Modifier.height(15.dp))
        for(exerciseGroup in workout.exerciseGroups){
            Row (horizontalArrangement = Arrangement.SpaceBetween,
                modifier = Modifier
                    .fillMaxWidth()
            ){
                Text(
                    modifier = Modifier.weight(1f),
                    text = exerciseGroup.name
                )
                Column( horizontalAlignment = Alignment.End) {
                    Text(
                        text = "Sets: ${exerciseGroup.sets}"
                    )
                    Spacer(modifier=Modifier.height(5.dp))
                    Text(
                        text = "Rest: ${exerciseGroup.restTimeInSec}s"
                    )
                }
            }
            if(exerciseGroup != workout.exerciseGroups.last()) Divider( modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 10.dp),thickness = 1.dp, color = Color.White)
        }
        Spacer(modifier=Modifier.height(10.dp))
    }

}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun WorkoutsScreen(
    navController: NavController,
    appViewModel: AppViewModel,
    onSyncClick: () -> Unit,
    onSaveClick: () -> Unit,
    onFileSelected: (Uri) -> Unit
) {
    val workouts = appViewModel.workouts
    var selectedWorkouts by remember { mutableStateOf(setOf<Workout>()) }
    var selectionMode by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("My Workout Assistant") },
                actions = {
                    Menu(
                        onSaveClick = onSaveClick,
                        onSyncClick = onSyncClick,
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
                        appViewModel.updateWorkouts(newWorkouts)
                        selectedWorkouts = emptySet()
                        selectionMode = false
                    }) {
                        Icon(imageVector = Icons.Default.Delete, contentDescription = "Delete")
                    }
                    Button(
                        modifier = Modifier.padding(5.dp),
                        onClick = {
                            for (workout in selectedWorkouts) {
                                appViewModel.updateWorkout(workout,workout.copy(enabled = true))
                            }
                            selectedWorkouts = emptySet()
                            selectionMode = false
                        }) {
                        Text("Enable")
                    }
                    Button(
                        modifier = Modifier.padding(5.dp),
                        onClick = {
                            for (workout in selectedWorkouts) {
                                appViewModel.updateWorkout(workout,workout.copy(enabled = false))
                            }
                            selectedWorkouts = emptySet()
                            selectionMode = false
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
                        navController.navigate(Screen.NewWorkout.route)
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
            SelectableList(
                selectionMode,
                modifier = Modifier
                    .fillMaxSize()
                    .padding(it)
                    .clickable {
                        if (selectionMode) {
                            selectionMode = false
                            selectedWorkouts = emptySet()
                        }
                    },
                items = workouts,
                selection = selectedWorkouts,
                onSelectionChange = { newSelection -> selectedWorkouts = newSelection} ,
                itemContent = { it ->
                    ExpandableCard(
                        isExpandable = it.exerciseGroups.isNotEmpty(),
                        modifier = Modifier
                            .fillMaxWidth()
                            .alpha(if (it.enabled) 1f else 0.4f)
                            .combinedClickable(
                                onClick = {
                                    if (selectionMode) {
                                        val newSelection =
                                            if (selectedWorkouts.contains(it)) {
                                                selectedWorkouts - it
                                            } else {
                                                selectedWorkouts + it
                                            }
                                        selectedWorkouts = newSelection
                                    } else {
                                        val workoutId = appViewModel.workouts.indexOf(it)
                                        navController.navigate(
                                            Screen.getRoute(
                                                Screen.WorkoutDetail,
                                                workoutId
                                            )
                                        )
                                    }
                                },
                                onLongClick = { if (!selectionMode) selectionMode = true }
                            ),
                        title = { modifier ->  WorkoutTitle(modifier,it) },
                        content = { WorkoutContent(it) }
                    )
                }
            )
        }
    }
}
