import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { ClaimDetailsComponent } from './claims/claim-details.component';

const routes: Routes = [
  { path: 'claims/:id', component: ClaimDetailsComponent }
];

@NgModule({ imports: [RouterModule.forRoot(routes)], exports: [RouterModule] })
export class AppRoutingModule {}
