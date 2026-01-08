package com.gabstra.myworkoutassistant.composables

import android.util.Log
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.TotalCaloriesBurnedRecord
import androidx.health.connect.client.records.WeightRecord
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.shared.DisabledContentGray

@Composable
fun HealthConnectHandler(
    appViewModel: AppViewModel,
    healthConnectClient: HealthConnectClient,
) {
    val requiredPermissions = setOf(
        HealthPermission.getWritePermission(ExerciseSessionRecord::class),
        HealthPermission.getWritePermission(HeartRateRecord::class),
        HealthPermission.getReadPermission(ExerciseSessionRecord::class),
        HealthPermission.getReadPermission(HeartRateRecord::class),
        HealthPermission.getWritePermission(TotalCaloriesBurnedRecord::class),
        HealthPermission.getWritePermission(WeightRecord::class),
    )

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        val hasAllPermissions = permissions.values.all { it }
        appViewModel.setHealthPermissions(hasAllPermissions)
    }

    LaunchedEffect(Unit) {
        val grantedPermissions = healthConnectClient.permissionController.getGrantedPermissions()
        val missingPermissions = requiredPermissions - grantedPermissions

        val hasAllPermissions = missingPermissions.isEmpty()
        appViewModel.setHealthPermissions(hasAllPermissions)
        appViewModel.setHealthPermissionsChecked()
    }

    if (appViewModel.checkedHealthPermission && !appViewModel.hasHealthPermissions) {
        StyledCard(
            modifier =  Modifier
            .fillMaxWidth()
            .padding(top = 10.dp)
            .padding(horizontal = 15.dp)
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(15.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Button(
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(
                        contentColor = MaterialTheme.colorScheme.background,
                        disabledContentColor = DisabledContentGray
                    ),
                    onClick = {
                        try {
                            permissionLauncher.launch(requiredPermissions.toTypedArray())
                        } catch (e: Exception) {
                            Log.e("MainActivity", "Error launching permission launcher", e)
                        }
                    }) {
                    Text("Grant Health Connect Permissions", color = MaterialTheme.colorScheme.onPrimary)
                }
            }
        }
    }
}
