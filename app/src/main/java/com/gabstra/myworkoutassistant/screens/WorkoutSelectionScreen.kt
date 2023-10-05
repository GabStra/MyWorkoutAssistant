package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.wear.compose.foundation.lazy.ScalingLazyColumn
import androidx.wear.compose.foundation.lazy.ScalingLazyListState
import androidx.wear.compose.foundation.lazy.items
import androidx.wear.compose.material.Chip
import androidx.wear.compose.material.ChipDefaults
import androidx.wear.compose.material.ListHeader
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.PositionIndicator
import androidx.wear.compose.material.Scaffold
import androidx.wear.compose.material.Text
import  androidx.wear.compose.foundation.lazy.rememberScalingLazyListState
import com.gabstra.myhomeworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.shared.Workout

@Composable
fun WorkoutListItem(workout: Workout, onItemClick: () -> Unit) {
    Chip(
        colors = ChipDefaults.chipColors(backgroundColor = Color.DarkGray),
        label = {
            Text(
                text = workout.name,
                style = MaterialTheme.typography.body2
            )
        },
        secondaryLabel = {
            Text(
                text = workout.description,
                style = MaterialTheme.typography.caption3,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis

            )
        },
        onClick = { onItemClick() },
        modifier = Modifier.size(160.dp,50.dp).padding(2.dp),
    )
}


@Composable
fun WorkoutSelectionScreen(navController: NavController, viewModel: AppViewModel) {
    val scalingLazyListState: ScalingLazyListState = rememberScalingLazyListState()
    val workouts = viewModel.workouts

    Scaffold(
        positionIndicator = {
            PositionIndicator(
                scalingLazyListState = scalingLazyListState
            )
        }
    ){
        ScalingLazyColumn(
            modifier = Modifier.padding(horizontal = 10.dp),
            state = scalingLazyListState
        ) {
            item { ListHeader { Text(
                text = "My Workout Assistant",
                textAlign = TextAlign.Center,
                style = MaterialTheme.typography.caption1,
            ) } }

            items(workouts) { workout ->
                WorkoutListItem(workout) {
                    viewModel.setWorkout(workout)
                    navController.navigate(Screen.WorkoutDetail.route)
                }
            }
        }
    }
}