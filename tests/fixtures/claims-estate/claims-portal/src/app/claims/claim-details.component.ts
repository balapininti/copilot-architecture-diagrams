import { Component } from '@angular/core';
import { ClaimService } from './claim.service';

@Component({ selector: 'app-claim-details', template: '<p>claim</p>' })
export class ClaimDetailsComponent {
  constructor(private claims: ClaimService) {}
}
