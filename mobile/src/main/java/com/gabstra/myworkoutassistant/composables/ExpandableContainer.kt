package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.ArrowDropUp
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import com.gabstra.myworkoutassistant.ui.theme.MediumDarkGray
import com.gabstra.myworkoutassistant.ui.theme.LightGray

@Composable
fun ExpandableContainer(
    modifier : Modifier = Modifier,
    isExpandable:Boolean = true,
    isOpen: Boolean = false,
    title: @Composable (modifier: Modifier) -> Unit,
    subContent : @Composable () -> Unit = {},
    content: @Composable () -> Unit,
    onOpen: () -> Unit = {},
    onClose: () -> Unit = {},
){
    var openStatus by remember {
        mutableStateOf(isOpen)
    }

    Column(
        modifier = modifier,
    ){
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.fillMaxWidth(),
        ){
            title(Modifier.weight(1f))
            if(isExpandable){
                IconButton(
                    onClick = {
                        openStatus = !openStatus
                        if(openStatus){
                            onOpen()
                        }else{
                            onClose()
                        }
                    }) {
                    Icon(imageVector = if(openStatus) Icons.Filled.ArrowDropDown else Icons.Filled.ArrowDropUp, contentDescription = "Back", tint = LightGray)
                }
            }
        }
        subContent()
        if(openStatus){
            Box{
                content()
            }
        }
    }
}