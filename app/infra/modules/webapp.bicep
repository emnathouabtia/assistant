@description('Base name for the app')
@minLength(3)
@maxLength(40)
param appName string 
param location string = resourceGroup().location
param tags object = {}

@allowed([
  'F1'
  'B1'
])

param skuName string = 'B1'

@allowed([
  'PYTHON|3.12'
  'NODE|20-lts'
])
param linuxFxVersion string = 'PYTHON|3.12'
var planName ='asp-${appName}'
var siteName = '${appName}-${uniqueString(resourceGroup().id)}'

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: planName
  location: location
  sku: {
    name: skuName
  }
  properties: {
    reserved: true
  }
}

resource site 'Microsoft.Web/sites@2023-12-01' = {
  name: siteName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: linuxFxVersion
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
    }
  }
}

output siteName string = site.name
output defaultHostName string = site.properties.defaultHostName
