import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../environments/environment';

@Injectable({ providedIn: 'root' })
export class ClaimService {
  constructor(private http: HttpClient) {}

  get(id: string) {
    return this.http.get(`${environment.apiBase}/claims/${id}`);
  }

  create(c: unknown) {
    return this.http.post(environment.apiBase + '/claims', c);
  }

  remove(id: string) {
    return this.http.delete(`${environment.apiBase}/claims/${id}`);
  }
}
