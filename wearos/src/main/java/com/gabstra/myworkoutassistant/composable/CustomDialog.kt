package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch


@Composable
fun CustomDialog(
    show : Boolean = false,
    title : String = "Confirm Exit",
    message : String = "Do you really want to exit?",
    handleNoClick: () -> Unit,
    handleYesClick: () -> Unit,
    closeTimerInMillis : Long = 0,
    handleOnAutomaticClose: () -> Unit = {}
) {
    var closeDialogJob by remember { mutableStateOf<Job?>(null) }
    val coroutineScope = rememberCoroutineScope()

    fun startAutomaticCloseTimer(){
        closeDialogJob?.cancel()
        closeDialogJob = coroutineScope.launch {
            delay(closeTimerInMillis)  // wait for 10 seconds
            handleOnAutomaticClose()
        }
    }

    LaunchedEffect(show){
        if(show && closeTimerInMillis > 0){
            startAutomaticCloseTimer()
        }
    }

    if (show) {
        Dialog(
            onDismissRequest = { handleNoClick() }
        ) {
            // Use a Box to add some padding around the content
            Box(modifier = Modifier
                .background(Color.Black)
                .fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center,
                ) {
                    Text(
                        text = title,
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.title3,
                        modifier = Modifier.padding(8.dp)
                    )
                    Text(
                        text =  message,
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.caption1,
                        modifier = Modifier.padding(8.dp)
                    )

                    Spacer(modifier = Modifier.height(20.dp))

                    Row(
                        horizontalArrangement = Arrangement.Center,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(8.dp)
                    ) {
                        Button(
                            onClick = {
                                closeDialogJob?.cancel()
                                handleNoClick()
                            },
                            modifier = Modifier.size(35.dp),
                            colors = ButtonDefaults.buttonColors(backgroundColor = MaterialTheme.colors.error)
                        ) {
                            Icon(imageVector = Icons.Default.Close, contentDescription = "Close")
                        }
                        Spacer(modifier = Modifier.width(10.dp))
                        Button(
                            onClick = {
                                closeDialogJob?.cancel()
                                handleYesClick()
                            },
                            modifier = Modifier.size(35.dp),
                            colors = ButtonDefaults.buttonColors(backgroundColor = MaterialTheme.colors.primary)
                        ) {
                            Icon(imageVector = Icons.Default.Check, contentDescription = "Done")
                        }
                    }
                }
            }
        }
    }
}